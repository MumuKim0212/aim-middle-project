"""[역할] 콘솔 화면: 상품 선택부터 실행·대출관리까지 사람이 직접 눌러 보는 대화형 메뉴(입력은 모두 검증 후 사용)."""
from __future__ import annotations

from decimal import Decimal as D

from . import catalog as C
from . import management as M
from .application import Session, products
from .calculators import kwon, won
from .database import Database
from .errors import LoanError
from .scenarios import run_all
from .security import get_logger

LOG = get_logger()
LINE = "─" * 60


def ask(prompt: str, default: str = "") -> str:
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def ask_int(prompt: str, default: int, lo: int, hi: int) -> int:
    while True:
        v = ask(prompt, str(default)).replace(",", "")
        if v.isdigit() and lo <= int(v) <= hi:
            return int(v)
        print(f"  ⚠ {lo:,} ~ {hi:,} 사이 숫자로 입력해 주세요.")


def ask_yes(prompt: str, default: bool = True) -> bool:
    v = ask(prompt + " (y/n)", "y" if default else "n").lower()
    return v.startswith("y")


def pick(title: str, options: list[str], default: int = 0) -> int:
    print(title)
    for i, o in enumerate(options, 1):
        print(f"  {i}. {o}")
    return ask_int("번호", default + 1, 1, len(options)) - 1


# ------------------------------------------------------------------ 신청 흐름
def apply_flow(db: Database, refi: bool) -> None:
    ps = products(db, refi)
    i = pick("\n[상품 선택]", [f"{p['name']} · 최대 {kwon(p['max_amount'])} | 기간 {min(p['term_options'])}~{max(p['term_options'])}개월 ({C.TYPE_NM[p['business_type']]})" for p in ps])
    p = ps[i]
    print(f"\n{LINE}\n{p['name']}\n  대상: {p['target_desc']}\n  금리(예시): 연 {D(str(p['rate_min'])):.2f}% ~ {D(str(p['rate_max'])):.2f}%\n  상환: {', '.join(p['repay_options'])}\n{LINE}")
    keys = ["직접 입력"] + list(C.SCENARIOS)
    k = pick("[체험 고객 선택]", ["직접 입력해서 체험"] + [C.SCENARIOS[x]["label"] for x in C.SCENARIOS])
    scn = None if k == 0 else keys[k]
    s = Session.start(db, p["product_id"], scn)
    try:
        run_steps(s)
    except LoanError as e:
        LOG.info("flow stopped %s %s", s.app_id, e.detail)
        print(f"\n  ⛔ {e.user_message}\n  → 처음으로 돌아갑니다.")


def run_steps(s: Session) -> None:
    sp = (s.scenario or {}).get("profile", {})
    if s.product["business_type"] == "POLICY":
        print("\n[G01 정책 자격 사전 확인]")
        married = ask_yes("기혼입니까", False)
        res = s.precheck(ask_yes("세대원 전원 무주택입니까"), married, ask_int("연 소득(원)", sp.get("income", 50_000_000), 0, 3_000_000_000), ask_int("순자산(원)", 200_000_000, 0, 10_000_000_000))
        for name, ok, code in res:
            print(f"  {'✓' if ok else '✕'} {name}" + ("" if ok else f" — {C.REASON_CODES[code][1]}"))
        if not all(r[1] for r in res):
            print("  정책 자격 미충족 → 처음으로 (일반대출로 다시 신청할 수 있습니다)")
            return
    print("\n[C02 약관·동의]  필수 항목은 모두 동의해야 진행됩니다.")
    agreed = {c: ask_yes(f"  [필수] {C.CONSENT_CODES[c][0]}") for c in s.required_consents()}
    agreed["PUBLIC_SCRAPING"] = ask_yes("  [선택] 공공기관 소득·재직 자동 연동", True)
    s.give_consents(agreed)
    if s.refi:
        print("\n[R03 기존 대출 조회] 마이데이터 조회 중…")
        for i, e in enumerate(s.fetch_existing(), 1):
            print(f"  {i}. {e['institution']} {e['kind']} {kwon(e['balance'])} 연 {e['rate']}% 남은 {e['remain']}개월 → {'대환 가능' if not e['codes'] else '대환 불가 ' + ', '.join(e['codes'])}")
        if not s.select_targets():
            print("  대환 가능한 대출이 없습니다. 기존 금융사에 금리인하요구권을 쓸 수 있습니다. → 처음으로")
            return
    print("\n[C03 고객정보 확인·적합성]")
    form = {"job": sp.get("job", "급여소득자"), "income": ask_int("연 소득(원)", sp.get("income", 50_000_000), 0, 3_000_000_000),
            "tenure": ask_int("재직 기간(개월)", sp.get("tenure", 36), 0, 600), "debt_monthly": ask_int("기존 대출 월 상환액(원)", sp.get("debt_monthly", 0), 0, 1_000_000_000)}
    if not s.refi:
        while True:
            amt = ask_int(f"희망 금액(원, 최대 {s.product['max_amount']:,})", min(sp.get("amount", s.default_amount()), s.product["max_amount"]), 0, 10_000_000_000)
            if amt <= s.product["max_amount"]:
                break
            print("  ⚠ 한도금액을 초과하였습니다.")
        form["amount"] = amt
    t = s.product["term_options"]
    dt = s.default_term()
    form["term"] = t[pick(f"기간 선택 (기본 {dt}개월)", [f"{x}개월" for x in t], t.index(dt) if dt in t else 0)] if len(t) > 1 else t[0]
    res, burden, plan = s.submit_profile(form)
    print(f"  적합성 1차 판정: {res} · 상환 부담률 {burden * 100:.0f}% (기준 70%)\n  ※ 본 결과는 입력한 정보에 따른 결과이므로 심사 결과는 달라질 수 있습니다.")
    if res == "UNSUITABLE":
        print(f"  금소법 적합성 원칙에 따라 현재 조건으로는 권유할 수 없습니다. 월 상환 가능액 {won(plan['budget'])}")
        if plan["max_amount"]:
            print(f"   ① 기간 유지 → 금액 {kwon(plan['max_amount'])} 이하")
        if plan["min_term"]:
            print(f"   ② 금액 유지 → 기간 {plan['min_term']}개월")
        if not ask_yes("  대출 업무 진행이 불가할 수 있는 점을 인지하고 심사 진행에 동의합니까", False):
            return
        s.submit_profile(form, ack_unsuitable=True)
    if s.flow_key == "POLICY" and not s.policy_check():
        print("  정책 자격 미충족 → 처음으로")
        return
    if s.flow_key == "INST_A":
        opts = s.guarantee_options()
        for o in opts:
            print(f"  {o['agency']}: {'가능' if o['ok'] else '불가'} 실질비용 {kwon(o['cost'])}")
        if not s.choose_guarantee():
            print("  보증 불가 → 처음으로")
            return
    if s.flow_key == "INST_B":
        org = C.ORGS[pick("[협약기관]", [n for _, n in C.ORGS])][0]
        if not s.affiliation(org, ask("사번", "A123456"), ("정규직", "계약직")[pick("고용 형태", ["정규직", "계약직"])]):
            print("  협약 대상 아님 → 처음으로")
            return
    print("\n[C04 증빙 제출]")
    files = {}
    for d in s.docs():
        path = "" if s.scenario else ask(f"  {d['name']} 파일 경로(엔터=건너뜀/자동연동)", "")
        if path:
            files[d["key"]] = path
    defects = s.submit_docs(files, auto_link=agreed.get("PUBLIC_SCRAPING", False))
    print("  결함 없음" if not defects else "  결함: " + ", ".join(defects))
    print("\n[C05 심사]")
    r = s.run_review()
    for name, mark, text in r.stages:
        print(f"  {'✓' if mark == 'ok' else '!' if mark == 'wa' else '✕'} {name}: {text}")
    if r.result in ("REJECTED", "DOCS_REQUIRED"):
        print(f"\n  결과: {'거절' if r.result == 'REJECTED' else '서류 보완 요청'}")
        for c in r.hard + r.docs:
            print(f"   - {c}: {C.REASON_CODES.get(c, ('', c))[1]}")
        return
    if s.refi:
        cmp = s.compare()
        print(f"\n[R09 유불리] {cmp['verdict']} · 순 절감액 {kwon(cmp['net'])} · 월 {won(cmp['old_monthly'])} → {won(cmp['new_monthly'])} · 기간 {cmp['term']}개월")
        if cmp["verdict"] != "BENEFICIAL":
            if not ask_yes("  불리하다는 고지를 확인했으며 그래도 진행합니까", False):
                return
            s.compare(confirm_unfavorable=True)
    else:
        cands = s.recommend()
        print(f"\n[C06 승인] 한도 {kwon(r.limit)} · 예상 금리 연 {r.rate}%")
        i = pick("[권장 상품]", [f"{c['variant']} 연 {c['rate']}% 월 {won(c['monthly'])} 총이자 {kwon(c['total_interest'])} — {' '.join(c['reasons'])}" for c in cands])
        s.choose(cands[i])
    terms = s.set_terms()
    final = s.price()
    print(f"\n[C07·C08] 금액 {kwon(terms['amount'])} · {terms['term']}개월 · {terms['repay']} · 최종 금리 연 {final}% · 월 {won(s.monthly())}")
    print("\n[C09 상품설명서 이해 확인] O 또는 X로 답하세요.")
    answers = [ask(f"  {q}", "") .upper() for q, _ in s.quiz()]
    s.explain(True, answers)
    print("\n[C10 약정]")
    s.sign_contract([ask_yes("  대출 조건·연체·수수료·약관 수령을 모두 확인했습니까")] * 5)
    if s.needs_collateral():
        s.set_collateral()
        print("  [C11] 담보·보증 설정 완료")
    s.execute(f"exec:{s.app_id}")
    print(f"\n✅ 실행 완료 · 계약 {s.contract} · 대출 계좌번호 {s.account_no} · 청약철회는 14일 안에 가능")


# ------------------------------------------------------------------ 대출관리
def manage(db: Database) -> None:
    accs = M.accounts(db)
    if not accs:
        print("  보유 대출이 없습니다. 먼저 신청을 완료하거나 '체험 고객 자동 실행'을 해 보세요.")
        return
    i = pick("\n[대출관리]", [f"{a['product_name']} · 대출 계좌번호 {a['account_masked']} · 잔액 {won(a['balance'])} · {a['status']}" for a in accs])
    a = accs[i]
    j = pick("[기능]", ["상환 스케줄 (전체)", "중도상환", "금리인하요구", "청약철회", "기간연장", "증명서 발급"])
    if j == 0:
        sc = M.full_schedule(a)
        print(f"  납입 완료 {sc['paid']}회 · 남은 {len(sc['rows'])}회 · 남은 원금 {won(sc['principal_sum'])} · 남은 이자 {won(sc['interest_sum'])}")
        for r in sc["rows"]:
            print(f"   {r['seq']:>3} {r['due_date']} 원금 {r['principal']:>12,} 이자 {r['interest']:>10,} 잔액 {r['balance_after']:>13,}")
    elif j == 1:
        amt = ask_int("상환 원금(원)", a["balance"], 1, a["balance"])
        q = M.prepay_quote(a, amt)
        print(f"  수수료 {won(q['fee'])}{' (면제)' if q['fee_free'] else ''} · 이자 {won(q['interest'])} · 총액 {won(q['total'])}")
        if ask_yes("  상환할까요"):
            key = f"prepay:{a['contract_no']}:{amt}:{a['balance']}"
            print(f"  잔액 {won(M.prepay(db, a['contract_no'], amt, key)['balance'])}")
    elif j == 2:
        res = M.rate_cut(db, a["contract_no"], ["승진·소득 증가"])
        print("  수용: 연 " + str(res["new_rate"]) + "%" if res["accepted"] else "  불수용: 새 등급의 가산금리가 현재보다 낮지 않습니다.")
    elif j == 3:
        res = M.withdraw(db, a["contract_no"])
        print(f"  {'철회 접수' if res['accepted'] else '철회 기한 경과'} · 기한 {res['deadline']} · 반환 {won(res['refund'])}")
    elif j == 4:
        print(f"  새 기간 {M.extend(db, a['contract_no'], 12)['new_term']}개월")
    else:
        print("  발급번호", M.certificate(db, a["contract_no"], "BALANCE"))


def demo_all(db: Database) -> None:
    print("\n[체험 고객 × 상품 21개 자동 실행]")
    ok = 0
    for r in run_all(db):
        ok += r["match"]
        print(f"  {'✓' if r['match'] else '✕'} {r['product']:<3} {r['scenario']:<9} 결과 {r['result']:<16} 기대 {r['expected']:<16} {', '.join(r['codes'])}")
    print(f"  정답표 일치 {ok}/21")


def main_menu(db: Database) -> None:
    while True:
        print(f"\n{LINE}\n OO은행 대출 서비스 (체험용 · 모든 값은 예시)\n{LINE}")
        try:
            k = pick("메뉴", ["대출 신청 (일반·정부·기관)", "대환 신청", "내 대출 관리", "체험 고객 21개 자동 실행", "감사 로그 무결성 검사", "종료"])
            if k == 0:
                apply_flow(db, refi=False)
            elif k == 1:
                apply_flow(db, refi=True)
            elif k == 2:
                manage(db)
            elif k == 3:
                demo_all(db)
            elif k == 4:
                ok, n = db.verify_audit_chain()
                print(f"  감사 로그 {n}건 · {'정상(위변조 없음)' if ok else '⚠ 해시 체인 불일치'}")
            else:
                print("종료합니다.")
                return
        except LoanError as e:
            print(f"  ⛔ {e.user_message}")
        except (KeyboardInterrupt, EOFError):
            print("\n종료합니다.")
            return
        except Exception:                                   # 예상 밖 오류: 화면엔 일반 안내만, 상세는 마스킹된 로그로
            LOG.exception("unexpected error")
            print("  ⛔ 일시적인 오류가 발생했습니다. 처음 메뉴로 돌아갑니다. (상세 내용은 로그에 기록)")
