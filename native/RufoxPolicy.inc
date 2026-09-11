// Included inside mozilla::psm in CertVerifier.cpp.
// MPL-2.0. Policy and log data derived from ISAIandCO/CAnttRUst.

Result CertVerifier::VerifyRufoxPolicy(
    NSSCertDBTrustDomain& trustDomain,
    const nsTArray<nsTArray<uint8_t>>& builtChain, Input sctsFromTLS,
    Time time, const char* hostname, const OriginAttributes& originAttributes,
    CertificateTransparencyInfo* ctInfo, bool rufoxOneShot) {
  bool protectedChain = false;
  for (const auto& bytes : builtChain) {
    Input cert;
    if (cert.Init(bytes.Elements(), bytes.Length()) != Success) {
      return Result::FATAL_ERROR_INVALID_ARGS;
    }
    protectedChain |= InputsAreEqual(cert, mRutheniumRootInput);
  }
  if (!protectedChain) {
    return Success;
  }

  nsAutoCString host(hostname ? hostname : "");
  ToLowerCase(host);
  if (!host.IsEmpty() && host.Last() == '.') {
    host.Truncate(host.Length() - 1);
  }
  // Exact hosts only; ordinary PKI validation is never overridden here.
  const nsCString& exceptions = originAttributes.mPrivateBrowsingId
                                   ? mRufoxPrivateExceptions : mRufoxExceptions;
  std::string_view hostView(host.get(), host.Length());
  std::string_view exceptionsView(exceptions.get(), exceptions.Length());
  bool zoneException = rufoxOneShot || rufox::HasException(exceptionsView, hostView, "zone", PR_Now() / PR_USEC_PER_SEC);
  bool ctException = rufoxOneShot || rufox::HasException(exceptionsView, hostView, "ct", PR_Now() / PR_USEC_PER_SEC);
  bool allowedZone = rufox::AllowedZone(hostView);
  CTVerifyResult result;
  nsAutoCString sctDetails;
  nsTArray<int16_t> operators;
  bool yandex = false;
  // All JSON strings below are constants or hex, never server-controlled text.
  auto finish = [&](const char* ctReason) -> Result {
    bool zoneBlocked = !allowedZone && !zoneException;
    bool ctBlocked = ctReason && !ctException;
    if (ctInfo) {
      nsCString& out = ctInfo->rufoxPolicy;
      out.AssignLiteral("{\"version\":1,\"state\":\"");
      out.Append(zoneBlocked || ctBlocked ? "blocked" :
                 zoneException || ctException ? "exception" : "allowed");
      out.AppendLiteral("\",\"zoneAllowed\":");
      out.Append(allowedZone ? "true" : "false");
      out.AppendLiteral(",\"zoneException\":");
      out.Append(zoneException ? "true" : "false");
      out.AppendLiteral(",\"ctException\":");
      out.Append(ctException ? "true" : "false");
      out.AppendLiteral(",\"oneShot\":");
      out.Append(rufoxOneShot ? "true" : "false");
      out.AppendLiteral(",\"hardened\":");
      out.Append(mRufoxHardened ? "true" : "false");
      out.AppendLiteral(",\"ctReason\":\"");
      out.Append(ctReason ? ctReason : "verified");
      out.AppendLiteral("\",\"operators\":");
      out.AppendInt(static_cast<int64_t>(operators.Length()));
      auto number = [&](const char* key, size_t value) {
        out.AppendLiteral(",\""); out.Append(key); out.AppendLiteral("\":");
        out.AppendInt(static_cast<int64_t>(value));
      };
      number("decodingErrors", result.decodingErrors);
      number("unknownLogs", result.sctsFromUnknownLogs);
      number("invalidSignatures", result.sctsWithInvalidSignatures);
      number("invalidTimestamps", result.sctsWithInvalidTimestamps);
      number("distrustedTimestamps", result.sctsWithDistrustedTimestamps);
      number("embedded", result.embeddedSCTs);
      number("tls", result.sctsFromTLSHandshake);
      number("ocsp", result.sctsFromOCSP);
      number("verifiedCount", result.verifiedScts.size());
      out.AppendLiteral(",\"scts\":["); out.Append(sctDetails);
      out.AppendLiteral("]}");
    }
    return zoneBlocked ? Result::ERROR_ADDITIONAL_POLICY_CONSTRAINT_FAILED :
           ctBlocked ? Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY : Success;
  };
  // Even an exception produces diagnostics; it changes enforcement, not evidence.
  if (builtChain.Length() < 2 || !mRufoxCTVerifier) {
    return finish("verifier-unavailable");
  }
  Input leaf, issuer;
  const auto& leafBytes = builtChain[0];
  const auto& issuerBytes = builtChain[1];
  if (leaf.Init(leafBytes.Elements(), leafBytes.Length()) != Success ||
      issuer.Init(issuerBytes.Elements(), issuerBytes.Length()) != Success) {
    return finish("certificate-unreadable");
  }
  BackCert issuerCert(issuer, EndEntityOrCA::MustBeCA, nullptr);
  BackCert leafCert(leaf, EndEntityOrCA::MustBeEndEntity, nullptr);
  if (issuerCert.Init() != Success || leafCert.Init() != Success) {
    return finish("certificate-unreadable");
  }
  Time notBefore(Time::uninitialized), notAfter(Time::uninitialized);
  if (ParseValidity(leafCert.GetValidity(), &notBefore, &notAfter) != Success) {
    return finish("certificate-unreadable");
  }
  Result rv = mRufoxCTVerifier->Verify(
      leaf, issuerCert.GetSubjectPublicKeyInfo(),
      trustDomain.GetSCTListFromCertificate(),
      trustDomain.GetSCTListFromOCSPStapling(), sctsFromTLS, time,
      trustDomain.GetDistrustAfterTime(), result);
  if (rv != Success) {
    return finish("verification-error");
  }
  size_t reported = 0;
  for (const auto& verified : result.verifiedScts) {
    for (const auto& log : kRufoxCTLogs) {
      if (verified.sct.logId.size() != sizeof(log.id) ||
          memcmp(verified.sct.logId.data(), log.id, sizeof(log.id)) != 0) {
        continue;
      }
      bool accepted = !(notAfter < TimeFromEpochInSeconds(log.start / 1000) ||
          notAfter >= TimeFromEpochInSeconds(log.end / 1000) ||
          TimeFromEpochInSeconds(verified.sct.timestamp / 1000) > notAfter ||
          (log.retired ? verified.sct.timestamp >= log.since
                       : verified.sct.timestamp < log.since));
      if (accepted) {
        yandex |= log.yandex;
        if (!operators.Contains(log.operatorId)) operators.AppendElement(log.operatorId);
      }
      // Keep the IPC payload bounded, without limiting policy verification.
      if (reported++ < 128) {
        if (!sctDetails.IsEmpty()) sctDetails.Append(',');
        sctDetails.AppendLiteral("{\"logId\":\"");
        constexpr char hex[] = "0123456789abcdef";
        for (uint8_t byte : log.id) {
          sctDetails.Append(hex[byte >> 4]); sctDetails.Append(hex[byte & 15]);
        }
        sctDetails.AppendLiteral("\",\"timestamp\":");
        sctDetails.AppendInt(static_cast<int64_t>(verified.sct.timestamp));
        sctDetails.AppendLiteral(",\"source\":\"");
        sctDetails.Append(verified.origin == SCTOrigin::Embedded ? "certificate" :
                          verified.origin == SCTOrigin::TLSExtension ? "tls" : "ocsp");
        sctDetails.AppendLiteral("\",\"accepted\":");
        sctDetails.Append(accepted ? "true}" : "false}");
      }
    }
  }
  return finish(!yandex ? "missing-yandex" :
                mRufoxHardened && operators.Length() < 2 ? "insufficient-operators" : nullptr);
}
