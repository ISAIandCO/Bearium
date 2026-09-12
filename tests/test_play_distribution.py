import copy
import tempfile
import unittest
from pathlib import Path
from scripts.resolve_play_source import validate_source
from scripts.upload_play import release_payload, publish

class DistributionTests(unittest.TestCase):
    def test_source_must_match_trusted_apk_run(self):
        run={'conclusion':'success','head_branch':'main','path':'.github/workflows/build-android.yml','event':'schedule','head_sha':'a'*40,'run_number':7}
        source={'source_commit':'a'*40,'version_code':7,'revision':'b'*40,'build_date':'20260912120000','version':'155.0.1','archive_url':'https://hg-edge.mozilla.org/releases/mozilla-release/archive/'+'b'*40+'.zip'}
        validate_source(run,source)
        for key,value in [('head_branch','feature'),('event','pull_request'),('conclusion','failure'),('head_sha','c'*40),('run_number',8)]:
            altered={**run,key:value}
            with self.assertRaises(ValueError): validate_source(altered,source)
        with self.assertRaises(ValueError): validate_source(run,{**source,'archive_url':'https://example.com/source.zip'})

    def test_rerun_and_downgrade_do_not_change_track(self):
        current={'releases':[{'versionCodes':['7'],'status':'completed'}]}
        self.assertIsNone(release_payload(7,'internal','completed','',current))
        self.assertIsNone(release_payload(6,'internal','completed','',current))
        self.assertEqual(release_payload(8,'internal','completed','',current)['releases'][0]['versionCodes'],['8'])

    def test_staged_rollout_preserves_previous_release(self):
        current={'releases':[{'versionCodes':['7'],'status':'completed'}]}
        result=release_payload(8,'production','inProgress','0.1',current)
        self.assertEqual(len(result['releases']),2)
        self.assertEqual(result['releases'][-1]['userFraction'],.1)
        with self.assertRaises(ValueError): release_payload(9,'production','completed','',result)
        with self.assertRaises(ValueError): release_payload(8,'production','inProgress','1',current)

    def test_draft_can_be_promoted(self):
        current={'releases':[{'versionCodes':['7'],'status':'draft'}]}
        self.assertEqual(release_payload(7,'internal','completed','',current)['releases'][0]['status'],'completed')

    def test_publish_uploads_validates_then_commits_without_canceling_review(self):
        class Response:
            ok=True;content=b'{}'
            def __init__(self,data): self.data=data
            def json(self): return self.data
        class Session:
            def __init__(self): self.calls=[]
            def request(self,method,url,**kwargs):
                self.calls.append((method,url,kwargs))
                if url.endswith('/edits'): return Response({'id':'edit'})
                if '/tracks/' in url: return Response({})
                if method=='GET': return Response({'bundles':[]})
                if 'uploadType=media' in url: return Response({'versionCode':7})
                return Response({})
            def delete(self,*args,**kwargs): raise AssertionError('Committed edits must not be deleted')
        session=Session()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'test.aab';path.write_bytes(b'fixture')
            publish(session,path,7,'internal','completed','')
        self.assertIn(':validate',session.calls[-2][1])
        self.assertTrue(session.calls[-1][1].endswith(':commit?changesInReviewBehavior=ERROR_IF_IN_REVIEW'))
        self.assertNotIn('json',session.calls[-1][2])

if __name__=='__main__': unittest.main()
