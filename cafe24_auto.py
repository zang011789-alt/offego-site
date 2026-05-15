# -*- coding: utf-8 -*-
"""
카페24 애널리틱스 자동 수집기
- 매일 09:00 실행 (Windows 작업 스케줄러)
- 리더뮨 + 아웃코마 각각 로그인 -> JWT 토큰 발급 -> 어제 데이터 수집
- 캠페인별 / 소재별 데이터 저장
"""
import sys, io, asyncio, json, aiohttp, logging
from datetime import date, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

OUTPUT_DIR = Path("C:/Users/zang0/Desktop/my-site")
LOG_FILE   = OUTPUT_DIR / "cafe24_auto_log.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

ACCOUNTS = [
    {"name": "ridermune", "mall_id": "garonge",  "pw": "flejabswm1@"},
    {"name": "outcoma",   "mall_id": "outcoma",  "pw": "eldhtmxhrwm1@"},
]

CA_BASE = "https://ca-internal.cafe24data.com"

async def get_token(page, mall_id):
    """카페24 로그인 후 ca-internal JWT 토큰 발급"""
    token_holder = [None]

    async def on_response(res):
        if "/auth/ca-token" in res.url:
            ct = res.headers.get("content-type", "")
            if "json" in ct:
                try:
                    body = await res.json()
                    if isinstance(body, dict) and "token" in body:
                        token_holder[0] = body["token"]
                except:
                    pass

    page.on("response", on_response)

    # 카페24 애널리틱스 페이지 로드 (토큰 자동 발급)
    url = f"https://{mall_id}.cafe24.com/disp/admin/shop1/menu/cafe24analytics"
    await page.goto(url, wait_until="domcontentloaded")
    # 토큰 올 때까지 최대 15초 대기
    for _ in range(30):
        if token_holder[0]:
            break
        await page.wait_for_timeout(500)

    page.remove_listener("response", on_response)
    return token_holder[0]

async def fetch_data(session, token, endpoint, params):
    """ca-internal API 호출"""
    url = CA_BASE + endpoint
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status != 200:
            log.warning(f"API {resp.status}: {endpoint}")
            return None
        return await resp.json()

async def collect_brand(account, yesterday_str, today_str):
    """브랜드별 데이터 수집"""
    log.info(f"[{account['name']}] 수집 시작 - 날짜: {yesterday_str}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx  = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()

        # 로그인
        await page.goto("https://eclogin.cafe24.com/Shop/", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await page.locator("input[type='text']").first.fill(account["mall_id"])
        await page.locator("input[type='password']").first.fill(account["pw"])
        await page.wait_for_timeout(300)
        await page.click("button.btnStrong")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await page.wait_for_timeout(2000)
        log.info(f"[{account['name']}] 로그인 완료")

        # JWT 토큰 발급
        token = await get_token(page, account["mall_id"])
        await browser.close()

    if not token:
        log.error(f"[{account['name']}] 토큰 발급 실패")
        return None

    log.info(f"[{account['name']}] 토큰 발급 완료")

    # API 호출
    # 기간: 어제 하루 (어제~어제)
    params_yesterday = {
        "device_type": "total",
        "start_date": yesterday_str,
        "end_date": yesterday_str,
        "sort": "order_amount",
        "order": "desc",
        "offset": 0,
        "limit": 200,
        "conversion_timeframe": "2h",
    }
    # 이번주 누적 (7일)
    week_ago = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    params_week = {**params_yesterday, "start_date": week_ago, "end_date": yesterday_str}

    result = {
        "brand": account["name"],
        "mall_id": account["mall_id"],
        "date": yesterday_str,
        "collected_at": today_str,
    }

    async with aiohttp.ClientSession() as session:
        # 캠페인별 (어제)
        data = await fetch_data(session, token, "/ca2/adsources/campaigns", params_yesterday)
        if data:
            result["campaigns_yesterday"] = data.get("campaigns", [])
            log.info(f"[{account['name']}] campaigns: {len(result['campaigns_yesterday'])}개")

        # 소재별 = utm_keyword(term) - 전체 소재명 포함 (어제)
        data = await fetch_data(session, token, "/ca2/adsources/terms", params_yesterday)
        if data:
            result["contents_yesterday"] = data.get("terms", [])
            log.info(f"[{account['name']}] terms(소재): {len(result['contents_yesterday'])}개")

        # 채널별 (어제)
        data = await fetch_data(session, token, "/ca2/adsources/channels", params_yesterday)
        if data:
            result["channels_yesterday"] = data.get("channels", [])
            log.info(f"[{account['name']}] channels: {len(result['channels_yesterday'])}개")

        # 매출 요약 (어제)
        data = await fetch_data(session, token, "/ca2/sales/highlights", params_yesterday)
        if data:
            result["sales_yesterday"] = data.get("highlights", [])

        # 캠페인별 (이번주)
        data = await fetch_data(session, token, "/ca2/adsources/campaigns", params_week)
        if data:
            result["campaigns_week"] = data.get("campaigns", [])

        # 소재별 = utm_keyword(term) - 전체 소재명 포함 (이번주)
        data = await fetch_data(session, token, "/ca2/adsources/terms", params_week)
        if data:
            result["contents_week"] = data.get("terms", [])

    return result

HISTORY_FILE = OUTPUT_DIR / "cafe24_history.json"
MAX_DAYS = 90

async def main():
    today     = date.today()
    yesterday = today - timedelta(days=1)
    today_str     = today.strftime("%Y-%m-%d")
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    log.info(f"=== 카페24 자동 수집 시작 ({today_str}) ===")

    all_results = {}
    for account in ACCOUNTS:
        try:
            result = await collect_brand(account, yesterday_str, today_str)
            if result:
                all_results[account["name"]] = result
        except Exception as e:
            log.error(f"[{account['name']}] 오류: {e}")
            import traceback
            traceback.print_exc()

    # 누적 히스토리 로드
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {}

    # 어제 날짜 키로 저장 (campaigns/contents/channels만, suffix 없이 단순화)
    history[yesterday_str] = {}
    for brand_name, result in all_results.items():
        history[yesterday_str][brand_name] = {
            "campaigns": result.get("campaigns_yesterday", []),
            "contents":  result.get("contents_yesterday", []),
            "channels":  result.get("channels_yesterday", []),
            "sales":     result.get("sales_yesterday", []),
        }

    # 90일 초과 항목 제거
    cutoff = (today - timedelta(days=MAX_DAYS)).strftime("%Y-%m-%d")
    history = {k: v for k, v in history.items() if k >= cutoff}

    # 히스토리 JSON 저장
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"히스토리 저장 완료: {HISTORY_FILE} ({len(history)}일치)")

    # 히스토리 JS 저장 (대시보드에서 로드)
    hist_js = OUTPUT_DIR / "cafe24_history.js"
    with open(hist_js, "w", encoding="utf-8") as f:
        f.write("window.CAFE24_HISTORY = ")
        json.dump(history, f, ensure_ascii=False, default=str)
        f.write(";")
    log.info(f"히스토리 JS 저장 완료: {hist_js}")

    # 하위 호환: 기존 cafe24_data.js도 최신 날짜 데이터로 유지
    js_file = OUTPUT_DIR / "cafe24_data.js"
    with open(js_file, "w", encoding="utf-8") as f:
        f.write("window.CAFE24_DATA = ")
        json.dump(all_results, f, ensure_ascii=False, default=str)
        f.write(";")
    log.info(f"=== 수집 완료 ===")

asyncio.run(main())
