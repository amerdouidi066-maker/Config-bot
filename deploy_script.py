async def run_in_cloudshell(link: str, project_id: str, token: str, email: str, region: str) -> Tuple[bool, str, str, int]:
    start_time = time.time()
    error_msg = ""
    service_url = ""
    vless = ""
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080"
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )
            page = await context.new_page()

            # 1. تسجيل الدخول مع كشف فوري لشاشة تسجيل الدخول
            logger.info("🌐 فتح رابط تسجيل الدخول...")
            await page.goto(link, timeout=60000, wait_until="networkidle")
            await asyncio.sleep(5)

            # التحقق من شاشة تسجيل الدخول (طريقة أقوى)
            page_text = await page.inner_text("body")
            if "Sign in" in page_text or "Use your Google Account" in page_text or "Email or phone" in page_text:
                await browser.close()
                return False, "", "❌ **الرابط منتهي الصلاحية أو غير صالح!**\nيرجى الحصول على رابط جديد من مختبر Qwiklabs (الرابط صالح لمدة 4 ساعات تقريباً).", int(time.time() - start_time)
            
            # تحقق إضافي من وجود حقل البريد الإلكتروني
            try:
                email_input = await page.wait_for_selector("input[type='email']", timeout=3000)
                if email_input:
                    await browser.close()
                    return False, "", "❌ **الرابط غير صالح!** (ظهرت شاشة تسجيل الدخول). يرجى استخدام رابط جديد.", int(time.time() - start_time)
            except:
                pass

            logger.info("✅ تم تسجيل الدخول بنجاح.")

            # 2. الدخول إلى Cloud Shell
            logger.info("📂 التوجه إلى Cloud Shell...")
            await page.goto("https://shell.cloud.google.com", timeout=60000, wait_until="networkidle")

            # 3. انتظار تحميل الطرفية (الباقي كما هو)
            logger.info("⏳ انتظار تحميل الطرفية...")
            terminal_ready = False
            for attempt in range(10):
                try:
                    await page.wait_for_selector(".xterm, .terminal, [role='textbox'], textarea", timeout=5000)
                    logger.info(f"✅ تم العثور على عنصر الطرفية (المحاولة {attempt+1})")
                    terminal_ready = True
                    break
                except:
                    logger.info(f"⏳ المحاولة {attempt+1}/10: لا يزال التحميل جارياً...")
            if not terminal_ready:
                logger.warning("⚠️ لم نتمكن من تأكيد تحميل الطرفية، ننتظر 15 ثانية ونكمل...")
                await asyncio.sleep(15)

            await asyncio.sleep(3)

            # 4. إعداد السكربت وحقنه (باقي الكود كما هو)
            with open("deploy_script.py", "r") as f:
                script_content = f.read()
            script_content = script_content.replace('os.environ.get("PROJECT_ID")', f'"{project_id}"')
            script_content = script_content.replace('os.environ.get("TOKEN")', f'"{token}"')
            script_content = script_content.replace('os.environ.get("EMAIL")', f'"{email}"')
            script_content = script_content.replace('os.environ.get("REGION")', f'"{region}"')
            b64_script = base64.b64encode(script_content.encode()).decode()

            commands = [
                f"echo '{b64_script}' | base64 -d > deploy.py",
                "python3 deploy.py",
                "cat result.txt"
            ]

            for cmd in commands:
                logger.info(f"⌨️ كتابة الأمر: {cmd[:50]}...")
                await page.keyboard.type(cmd)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)

            # 5. انتظار النتيجة
            logger.info("⏳ انتظار اكتمال النشر وظهور النتيجة (حتى 3 دقائق)...")
            try:
                await page.wait_for_selector("text=/SERVICE_URL:|VLESS:/", timeout=180000)
                logger.info("✅ تم العثور على النتيجة.")
            except:
                logger.warning("⚠️ لم يتم العثور على النتيجة خلال المهلة.")

            await asyncio.sleep(3)
            terminal_text = await page.evaluate("() => document.body.innerText")
            await browser.close()

            # استخراج النتيجة
            service_match = re.search(r'SERVICE_URL:\s*(https://[a-zA-Z0-9\-]+\.run\.app)', terminal_text)
            vless_match = re.search(r'VLESS:\s*(vless://[^\s]+)', terminal_text)

            if service_match and vless_match:
                service_url = service_match.group(1)
                vless = vless_match.group(1)
                return True, service_url, vless, int(time.time() - start_time)
            else:
                return False, "", f"⚠️ لم أتمكن من استخراج النتيجة. آخر ما ظهر:\n```\n{terminal_text[-800:]}\n```", int(time.time() - start_time)

    except Exception as e:
        return False, "", str(e), int(time.time() - start_time)