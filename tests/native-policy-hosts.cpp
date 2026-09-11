#include "RufoxPolicyHelpers.h"
#include <cassert>
using namespace mozilla::psm::rufox;
int main() {
  assert(AllowedZone("bank.ru"));
  assert(AllowedZone("a.bank.su"));
  assert(AllowedZone("xn--e1afmkfd.xn--p1ai"));
  for (auto host : {"ru", ".ru", "bank.ru.evil.com", "notru", "127.0.0.1", "::1", ""}) {
    assert(!AllowedZone(host));
  }
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
