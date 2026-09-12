#!/usr/bin/env python3
"""Publish an already validated AAB through Android Publisher edits.

No application creation, key enrollment or store declarations are automated.
Reruns reuse the versionCode and never downgrade a newer track release.
"""
import argparse
import hashlib
import json
import os
import re

PACKAGE='app.bearium.browser'
API='https://androidpublisher.googleapis.com/androidpublisher/v3/applications/'+PACKAGE
UPLOAD='https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications/'+PACKAGE


def release_payload(code, track, status, fraction, current):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',track): raise ValueError('Invalid track ID')
    if status not in ('draft','completed','inProgress'): raise ValueError('Use draft, completed or inProgress')
    release={'versionCodes':[str(code)],'status':status}
    if status=='inProgress':
        value=float(fraction)
        if not 0<value<1: raise ValueError('Staged rollout fraction must be between 0 and 1')
        release['userFraction']=value
    elif fraction:
        raise ValueError('USER_FRACTION applies only to inProgress')
    releases=current.get('releases',[])
    codes=[int(v) for r in releases for v in r.get('versionCodes',[])]
    if codes and max(codes)>code: return None
    if any(str(code) in r.get('versionCodes',[]) and r.get('status')==status and r.get('userFraction')==release.get('userFraction') for r in releases):
        return None
    if any(r.get('status')=='inProgress' and str(code) not in r.get('versionCodes',[]) for r in releases):
        raise ValueError('Finish or halt the existing staged rollout before publishing a different version')
    prior=[r for r in releases if r.get('status')=='completed' and str(code) not in r.get('versionCodes',[])] if status=='inProgress' else []
    return {'track':track,'releases':prior+[release]}


def publish(session, aab, code, track, status, fraction):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',track): raise ValueError('Invalid track ID')
    def request(method,url,**kwargs):
        response=session.request(method,url,timeout=300,**kwargs)
        # Do not include credentials or response bodies in exception output.
        if not response.ok: raise RuntimeError(f'Android Publisher returned HTTP {response.status_code} during {method} {url.split("?")[0]}')
        return response.json() if response.content else {}
    edit=request('POST',API+'/edits',json={})['id']
    base=API+'/edits/'+edit
    committed=False
    try:
        current=request('GET',base+'/tracks/'+track)
        payload=release_payload(code,track,status,fraction,current)
        if payload is None:
            print('Track already contains this release or a newer version; no changes made')
            return
        bundles=request('GET',base+'/bundles').get('bundles',[])
        if not any(int(b['versionCode'])==code for b in bundles):
            with aab.open('rb') as stream:
                uploaded=request('POST',UPLOAD+'/edits/'+edit+'/bundles?uploadType=media',data=stream,headers={'Content-Type':'application/octet-stream'})
            if int(uploaded['versionCode'])!=code: raise ValueError('Uploaded AAB has an unexpected versionCode')
        request('PUT',base+'/tracks/'+track,json=payload)
        request('POST',base+':validate')
        request('POST',base+':commit?changesInReviewBehavior=ERROR_IF_IN_REVIEW')
        committed=True
        print(f'Play edit committed: {PACKAGE}, versionCode={code}, track={track}, status={status}')
        print('Google review and account requirements can still delay availability')
    finally:
        if not committed:
            # A failed/unused edit must not block subsequent manual or CI work.
            try: session.delete(base,timeout=30)
            except Exception: pass


def main():
    from pathlib import Path
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    p=argparse.ArgumentParser()
    p.add_argument('--aab',type=Path,required=True)
    p.add_argument('--version-code',type=int,required=True)
    a=p.parse_args()
    report=json.loads(a.aab.with_suffix('.validation.json').read_text())
    if report.get('package')!=PACKAGE or report.get('versionCode')!=a.version_code or report.get('static16KBChecks')!='passed':
        raise ValueError('Missing matching bundle validation report')
    if report.get('aabSha256')!=hashlib.sha256(a.aab.read_bytes()).hexdigest():
        raise ValueError('AAB content does not match the validation report')
    info=json.loads(os.environ['BEARIUM_PLAY_SERVICE_ACCOUNT_JSON'])
    # Never send the private key to an endpoint selected by the secret document.
    if info.get('token_uri')!='https://oauth2.googleapis.com/token': raise ValueError('Unexpected OAuth token endpoint')
    credentials=service_account.Credentials.from_service_account_info(info,scopes=['https://www.googleapis.com/auth/androidpublisher'])
    with AuthorizedSession(credentials) as session:
        publish(session,a.aab,a.version_code,os.environ.get('BEARIUM_PLAY_TRACK','internal'),os.environ.get('BEARIUM_PLAY_RELEASE_STATUS','completed'),os.environ.get('BEARIUM_PLAY_USER_FRACTION',''))

if __name__=='__main__': main()
