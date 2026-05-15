# -*- coding: utf-8 -*-
"""
카페24 과거 데이터 백필 (1회성 실행)
- 오늘 기준 최근 7일 (오늘 제외) 데이터 수집
- 이미 존재하는 날짜는 건너뜀
"""
import sys, io, asyncio, json, aiohttp, logging
from datetime import date, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

OUTPUT_DIR  = Path("C:/Users/zang0/Desktop/my-site")
HISTORY_FILE = OUTPUT_DIR / "cafe24_history.json"
CA_BASE     = "https://ca-internal.cafe24data.com"
DAYS        = 7  # 최근 7일

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

ACCOUNTS = [
    {"name": "ridermune", "mall_id": "garonge",  "pw": "flejabswm1@"},
    {"name": "outcoma",   "mall_id": "outcoma",  "pw": "eldhtmxhrwm1@"},
]

async def get_token(mall_id, pw):
    """로그인 후 JWT 토큰 발급"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx  = await browser.new_context()
        page = await ctx.new_page()
        token_holder = [None]

        async def on_response(res):
            if "/auth/ca-token" in res.url:
                try:
                    body = await res.json()
                    if isinstance(body, dict) and "token" in body:
                        token_holder[0] = body["token"]
                except: pass

        page.on("response", on_response)
        await page.goto("https://eclogin.cafe24.com/Shop/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await page.locator("input[type='text']").first.fill(mall_id)
        await page.locator("input[type='password']").first.fill(pw)
        await page.wait_for_timeout(300)
        await page.click("button.btnStrong")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await page.wait_for_timeout(2000)
        await page.goto(
            f"https://{mall_id}.cafe24.com/disp/admin/shop1/menu/cafe24analytics",
            wait_until="domcontentloaded"
        )
        for _ in range(30):
            if token_holder[0]: break
            await page.wait_for_timeout(500)
        await browser.close()
        return token_holder[0]

async def fetch(session, token, endpoint, params):
    url = CA_BASE + endpoint
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status != 200:
            return None
        return await resp.json()

async def collect_day(session, token, account_name, target_str):
    """특정 날짜 하루 데이터 수집"""
    params = {
        "device_type": "total",
        "start_date": target_str,
        "end_date": target_str,
        "sort": "order_amount",
        "order": "desc",
        "offset": 0,
        "limit": 200,
        "conversion_timeframe": "2h",
    }
    result = {}

    data = await fetch(session, token, "/ca2/adsources/campaigns", params)
    result["campaigns"] = data.get("campaigns", []) if data else []

    data = await fetch(session, token, "/ca2/adsources/terms", params)
    result["contents"] = data.get("terms", []) if data else []

    data = await fetch(session, token, "/ca2/adsources/channels", params)
    result["channels"] = data.get("channels", []) if data else []

    log.info(f"  [{account_name}] {target_str}: campaigns={len(result['campaigns'])}, terms={len(result['contents'])}, channels={len(result['channels'])}")
    return result

async def main():
    today = date.today()

    # 히스토리 로드
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        log.info(f"기존 히스토리 로드: {len(history)}일치")
    else:
        history = {}

    # 수집 대상 날짜 목록 (오늘 제외 최근 7일)
    target_dates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(1, DAYS + 1)
    ]
    # 항상 전체 재수집 (기여기간 변경 등으로 덮어써야 할 때)
    missing  = target_dates
    existing = []

    log.info(f"대상 {DAYS}일: {target_dates[0]} ~ {target_dates[-1]} (전체 재수집)")
    log.info(f"수집 필요: {missing}")

    if not missing:
        log.info("수집할 날짜 없음. 종료.")
        return

    # 브랜드별 토큰 획득 (한 번씩만)
    log.info("\n=== 토큰 발급 ===")
    tokens = {}
    for account in ACCOUNTS:
        log.info(f"[{account['name']}] 로그인 중...")
        token = await get_token(account["mall_id"], account["pw"])
        if token:
            tokens[account["name"]] = token
            log.info(f"[{account['name']}] 토큰 발급 완료")
        else:
            log.error(f"[{account['name']}] 토큰 발급 실패")

    # 날짜별 수집
    log.info(f"\n=== 데이터 수집 시작 ({len(missing)}일) ===")
    async with aiohttp.ClientSession() as session:
        for target_str in missing:
            log.info(f"\n--- {target_str} ---")
            history[target_str] = {}
            for account in ACCOUNTS:
                token = tokens.get(account["name"])
                if not token:
                    continue
                try:
                    history[target_str][account["name"]] = await collect_day(
                        session, token, account["name"], target_str
                    )
                except Exception as e:
                    log.error(f"  [{account['name']}] {target_str} 오류: {e}")
                    history[target_str][account["name"]] = {"campaigns": [], "contents": [], "channels": []}

    # 90일 초과 제거
    cutoff = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    history = {k: v for k, v in history.items() if k >= cutoff}

    # 저장
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"\n히스토리 JSON 저장: {len(history)}일치")

    hist_js = OUTPUT_DIR / "cafe24_history.js"
    with open(hist_js, "w", encoding="utf-8") as f:
        f.write("window.CAFE24_HISTORY = ")
        json.dump(history, f, ensure_ascii=False, default=str)
        f.write(";")
    log.info(f"히스토리 JS 저장 완료: {hist_js}")

    dates_sorted = sorted(history.keys())
    log.info(f"보유 날짜: {dates_sorted[0]} ~ {dates_sorted[-1]} ({len(history)}일)")

asyncio.run(main())
