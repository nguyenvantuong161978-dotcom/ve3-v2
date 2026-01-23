// ============================================================
// TEST SCRIPT: Paste và gửi prompt trên Google Flow
// Cách dùng: Mở https://labs.google/fx/vi/tools/flow
//            F12 > Console > Paste script này > Enter
// ============================================================

(async function testPastePrompt() {
    const PROMPT = "Portrait on pure white background, 85mm lens, 64-year-old Caucasian woman named Ivy, short silver-gray pixie cut hair, warm hazel eyes with laugh lines, gentle smile, wearing a navy blue cardigan over a cream blouse, soft natural lighting, photorealistic, high detail";

    console.log("=".repeat(60));
    console.log("TEST: Paste và gửi prompt");
    console.log("=".repeat(60));

    // Helper: Đợi element
    function waitForElement(selector, timeout = 10000) {
        return new Promise((resolve, reject) => {
            const startTime = Date.now();
            const check = () => {
                const el = document.querySelector(selector);
                if (el) {
                    resolve(el);
                } else if (Date.now() - startTime > timeout) {
                    reject(new Error(`Timeout waiting for: ${selector}`));
                } else {
                    setTimeout(check, 100);
                }
            };
            check();
        });
    }

    // Helper: Sleep
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));

    try {
        // STEP 1: Tìm textarea/input
        console.log("\n[STEP 1] Tìm input field...");

        // Các selector có thể dùng
        const selectors = [
            'textarea[placeholder*="prompt"]',
            'textarea[placeholder*="Prompt"]',
            'textarea[aria-label*="prompt"]',
            'div[contenteditable="true"]',
            'textarea',
            'input[type="text"]'
        ];

        let inputEl = null;
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
                console.log(`  [OK] Tìm thấy: ${sel}`);
                inputEl = el;
                break;
            }
        }

        if (!inputEl) {
            // Thử tìm qua aria-label
            const allInputs = document.querySelectorAll('textarea, input, [contenteditable="true"]');
            console.log(`  Tìm thấy ${allInputs.length} input elements`);
            allInputs.forEach((el, i) => {
                console.log(`  [${i}] ${el.tagName} - placeholder="${el.placeholder || ''}" aria="${el.getAttribute('aria-label') || ''}"`);
            });

            if (allInputs.length > 0) {
                inputEl = allInputs[0];
                console.log(`  [FALLBACK] Dùng element đầu tiên`);
            }
        }

        if (!inputEl) {
            throw new Error("Không tìm thấy input field!");
        }

        // STEP 2: Focus vào input
        console.log("\n[STEP 2] Focus vào input...");
        inputEl.focus();
        inputEl.click();
        await sleep(500);
        console.log("  [OK] Focused");

        // STEP 3: Clear nội dung cũ
        console.log("\n[STEP 3] Clear nội dung cũ...");
        if (inputEl.tagName === 'TEXTAREA' || inputEl.tagName === 'INPUT') {
            inputEl.value = '';
        } else {
            inputEl.innerHTML = '';
            inputEl.textContent = '';
        }
        await sleep(200);
        console.log("  [OK] Cleared");

        // STEP 4: Paste prompt - Thử nhiều cách
        console.log("\n[STEP 4] Paste prompt...");
        console.log(`  Prompt length: ${PROMPT.length} chars`);

        // Cách 1: Direct value assignment
        console.log("  [TRY 1] Direct value...");
        if (inputEl.tagName === 'TEXTAREA' || inputEl.tagName === 'INPUT') {
            inputEl.value = PROMPT;
        } else {
            inputEl.textContent = PROMPT;
        }
        await sleep(300);

        // Kiểm tra
        let currentValue = inputEl.value || inputEl.textContent || inputEl.innerText;
        console.log(`  Current value length: ${currentValue.length}`);

        if (currentValue.length < 10) {
            // Cách 2: Input event
            console.log("  [TRY 2] Input event...");
            inputEl.focus();

            // Dispatch input event
            const inputEvent = new InputEvent('input', {
                bubbles: true,
                cancelable: true,
                inputType: 'insertText',
                data: PROMPT
            });
            inputEl.dispatchEvent(inputEvent);
            await sleep(300);
        }

        currentValue = inputEl.value || inputEl.textContent || inputEl.innerText;
        if (currentValue.length < 10) {
            // Cách 3: execCommand
            console.log("  [TRY 3] execCommand...");
            inputEl.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('insertText', false, PROMPT);
            await sleep(300);
        }

        currentValue = inputEl.value || inputEl.textContent || inputEl.innerText;
        if (currentValue.length < 10) {
            // Cách 4: Clipboard API
            console.log("  [TRY 4] Clipboard paste...");
            try {
                await navigator.clipboard.writeText(PROMPT);
                inputEl.focus();
                document.execCommand('paste');
                await sleep(300);
            } catch (e) {
                console.log("  Clipboard error:", e.message);
            }
        }

        // Verify
        currentValue = inputEl.value || inputEl.textContent || inputEl.innerText;
        console.log(`  [RESULT] Final value length: ${currentValue.length}`);
        console.log(`  [RESULT] First 50 chars: "${currentValue.substring(0, 50)}..."`);

        if (currentValue.length < 10) {
            console.log("  [FAIL] Không paste được prompt!");
            return;
        }
        console.log("  [OK] Paste thành công!");

        // STEP 5: Trigger React/Angular state update
        console.log("\n[STEP 5] Trigger state update...");

        // Dispatch events để framework detect changes
        ['input', 'change', 'keyup', 'keydown'].forEach(eventType => {
            const event = new Event(eventType, { bubbles: true });
            inputEl.dispatchEvent(event);
        });
        await sleep(500);
        console.log("  [OK] Events dispatched");

        // STEP 6: Tìm nút gửi
        console.log("\n[STEP 6] Tìm nút gửi...");

        const buttonSelectors = [
            'button[aria-label*="Send"]',
            'button[aria-label*="send"]',
            'button[aria-label*="Generate"]',
            'button[aria-label*="Tạo"]',
            'button[type="submit"]',
            'button:has(svg)',  // Button có icon
            'button'
        ];

        let sendBtn = null;
        for (const sel of buttonSelectors) {
            try {
                const btns = document.querySelectorAll(sel);
                for (const btn of btns) {
                    const text = (btn.textContent || btn.getAttribute('aria-label') || '').toLowerCase();
                    if (text.includes('send') || text.includes('generate') || text.includes('tạo') || text.includes('gửi')) {
                        sendBtn = btn;
                        console.log(`  [OK] Tìm thấy: "${text}"`);
                        break;
                    }
                }
                if (sendBtn) break;
            } catch (e) {}
        }

        if (!sendBtn) {
            console.log("  [WARN] Không tìm thấy nút gửi, thử Enter...");
        }

        // STEP 7: Gửi prompt
        console.log("\n[STEP 7] Gửi prompt...");

        if (sendBtn) {
            console.log("  [TRY] Click send button...");
            sendBtn.click();
        } else {
            console.log("  [TRY] Press Enter...");
            const enterEvent = new KeyboardEvent('keydown', {
                key: 'Enter',
                code: 'Enter',
                keyCode: 13,
                which: 13,
                bubbles: true
            });
            inputEl.dispatchEvent(enterEvent);
        }

        console.log("\n" + "=".repeat(60));
        console.log("TEST HOÀN TẤT - Kiểm tra xem request có được gửi không");
        console.log("=".repeat(60));

    } catch (error) {
        console.error("\n[ERROR]", error.message);
        console.error(error.stack);
    }
})();
