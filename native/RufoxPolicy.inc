// Included inside mozilla::psm in CertVerifier.cpp.
// MPL-2.0. Policy and log data derived from ISAIandCO/CAnttRUst.

Result CertVerifier::VerifyRufoxPolicy(
    NSSCertDBTrustDomain& trustDomain,
    const nsTArray<nsTArray<uint8_t>>& builtChain, Input sctsFromTLS,
    Time time, const char* hostname, const OriginAttributes& originAttributes) {
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
  // Exact hosts only. A permission never covers sibling names in a SAN or
  // subdomains. The ordinary certificate hostname check still runs afterward.
  const nsCString& exceptions = originAttributes.mPrivateBrowsingId
                                   ? mRufoxPrivateExceptions
                                   : mRufoxExceptions;
  std::string_view hostView(host.get(), host.Length());
  std::string_view exceptionsView(exceptions.get(), exceptions.Length());
  bool zoneException = rufox::HasException(exceptionsView, hostView, "zone");
  bool ctException = rufox::HasException(exceptionsView, hostView, "ct");
  bool allowedZone = rufox::AllowedZone(hostView);
  if (!zoneException && !allowedZone) {
    return Result::ERROR_ADDITIONAL_POLICY_CONSTRAINT_FAILED;
  }
  if (ctException) {
    return Success;
  }
  if (builtChain.Length() < 2 || !mRufoxCTVerifier) {
    return Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY;
  }
  Input leaf, issuer;
  const auto& leafBytes = builtChain[0];
  const auto& issuerBytes = builtChain[1];
  if (leaf.Init(leafBytes.Elements(), leafBytes.Length()) != Success ||
      issuer.Init(issuerBytes.Elements(), issuerBytes.Length()) != Success) {
    return Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY;
  }
  BackCert issuerCert(issuer, EndEntityOrCA::MustBeCA, nullptr);
  BackCert leafCert(leaf, EndEntityOrCA::MustBeEndEntity, nullptr);
  if (issuerCert.Init() != Success || leafCert.Init() != Success) {
    return Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY;
  }
  Time notBefore(Time::uninitialized), notAfter(Time::uninitialized);
  if (ParseValidity(leafCert.GetValidity(), &notBefore, &notAfter) != Success) {
    return Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY;
  }
  CTVerifyResult result;
  Result rv = mRufoxCTVerifier->Verify(
      leaf, issuerCert.GetSubjectPublicKeyInfo(),
      trustDomain.GetSCTListFromCertificate(),
      trustDomain.GetSCTListFromOCSPStapling(), sctsFromTLS, time,
      trustDomain.GetDistrustAfterTime(), result);
  if (rv != Success) {
    return Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY;
  }
  bool yandex = false;
  nsTArray<int16_t> operators;
  for (const auto& verified : result.verifiedScts) {
    for (const auto& log : kRufoxCTLogs) {
      if (verified.sct.logId.size() != sizeof(log.id) ||
          memcmp(verified.sct.logId.data(), log.id, sizeof(log.id)) != 0) {
        continue;
      }
      // The log shard interval describes certificate expiry, not SCT issuance.
      if (notAfter < TimeFromEpochInSeconds(log.start / 1000) ||
          notAfter >= TimeFromEpochInSeconds(log.end / 1000) ||
          TimeFromEpochInSeconds(verified.sct.timestamp / 1000) > notAfter ||
          (log.retired ? verified.sct.timestamp >= log.since
                       : verified.sct.timestamp < log.since)) {
        continue;
      }
      yandex |= log.yandex;
      if (!operators.Contains(log.operatorId)) {
        operators.AppendElement(log.operatorId);
      }
    }
  }
  return yandex && (!mRufoxHardened || operators.Length() >= 2)
             ? Success
             : Result::ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY;
}
