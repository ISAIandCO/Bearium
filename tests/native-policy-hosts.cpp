#include "RufoxPolicyHelpers.h"
#include <cassert>
using namespace mozilla::psm::rufox;
int main() {
  for (std::string_view pin : {
      "bbbde2103e790b999ec62bd03cf625a5a2e7c316e10afe6a490eedead8b3fd9b",
      "2155785036c900dbb5f1bb2a1569c80c55595bd6bf94867a29bbddbc7d88a3f2"}) {
    uint8_t digest[32];
    auto nibble = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
    for (size_t i = 0; i < 32; i++) digest[i] = nibble(pin[i * 2]) * 16 + nibble(pin[i * 2 + 1]);
    assert(IsProtectedIntermediateHash(digest, sizeof(digest)));
    digest[31] ^= 1;
    assert(!IsProtectedIntermediateHash(digest, sizeof(digest)));
    assert(!IsProtectedIntermediateHash(digest, 31));
  }
  assert(!IsProtectedIntermediateHash(nullptr, 32));
  uint8_t unknownDigest[32] = {};
  assert(!IsProtectedIntermediateHash(unknownDigest, sizeof(unknownDigest)));
  assert(AllowedZone("bank.ru"));
  assert(AllowedZone("a.bank.su"));
  assert(AllowedZone("xn--e1afmkfd.xn--p1ai"));
  for (auto host : {"ru", ".ru", "bank.ru.evil.com", "notru", "127.0.0.1", "::1", ""}) {
    assert(!AllowedZone(host));
  }
  assert(HasException("bank.ru|all|200", "bank.ru", "ct", 199));
  assert(!HasException("bank.ru|all|200", "bank.ru", "ct", 200));
  assert(!HasException("bank.ru|all|oops", "bank.ru", "ct", 199));
  assert(!HasException("bank.ru|all|200", "bank.ru", "ct"));
  auto rules = "bank.ru|zone,other.com|all,ct.ru|ct";
  assert(HasException(rules, "bank.ru", "zone"));
  assert(!HasException(rules, "bank.ru", "ct"));
  assert(HasException(rules, "ct.ru", "ct"));
  assert(!HasException(rules, "ct.ru", "zone"));
  assert(HasException(rules, "other.com", "ct"));
  assert(HasException(rules, "other.com", "zone"));
  for (auto host : {"a.other.com", "other.com.evil.ru", "other.co", "", "other.com|all"}) {
    assert(!HasException(rules, host, "ct"));
  }
  assert(!HasException("*.ru|all,.ru|all", "bank.ru", "zone"));
  assert(!HasException("bank.ru|unknown", "bank.ru", "ct"));
  assert(HasException("127.0.0.1|all", "127.0.0.1", "zone"));
  assert(HasException("::1|all", "::1", "zone"));
}
