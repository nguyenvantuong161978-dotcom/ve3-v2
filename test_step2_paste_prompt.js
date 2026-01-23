// STEP 2: Paste prompt vào input
// Paste vào Console (F12) sau khi đã chọn mode Tạo hình ảnh

(function() {
    // QUAN TRỌNG: Thêm dấu cách ở cuối để Enter hoạt động
    const PROMPT = "Portrait on pure white background, 85mm lens, 64-year-old woman ";

    console.log("=== STEP 2: Paste prompt ===");
    console.log(`Prompt: "${PROMPT}"`);

    // Tìm input field
    const selectors = [
        'textarea',
        'div[contenteditable="true"]',
        'input[type="text"]',
        '[role="textbox"]'
    ];

    let inputEl = null;
    for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        if (els.length > 0) {
            inputEl = els[0];
            console.log(`[OK] Tìm thấy: ${sel} (${els.length} elements)`);
            break;
        }
    }

    if (!inputEl) {
        console.log("[FAIL] Không tìm thấy input field!");
        return;
    }

    // Focus
    inputEl.focus();
    inputEl.click();
    console.log("Focused input");

    // Clear
    if (inputEl.tagName === 'TEXTAREA' || inputEl.tagName === 'INPUT') {
        inputEl.value = '';
    } else {
        inputEl.innerHTML = '';
        inputEl.textContent = '';
    }

    // Paste - Thử nhiều cách
    console.log("Thử paste...");

    // Cách 1: Direct value
    if (inputEl.tagName === 'TEXTAREA' || inputEl.tagName === 'INPUT') {
        inputEl.value = PROMPT;
        console.log("  [TRY 1] inputEl.value = PROMPT");
    } else {
        inputEl.textContent = PROMPT;
        console.log("  [TRY 1] inputEl.textContent = PROMPT");
    }

    // Cách 2: Input event
    const inputEvent = new InputEvent('input', {
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: PROMPT
    });
    inputEl.dispatchEvent(inputEvent);
    console.log("  [TRY 2] dispatchEvent(InputEvent)");

    // Cách 3: execCommand
    document.execCommand('selectAll', false, null);
    document.execCommand('insertText', false, PROMPT);
    console.log("  [TRY 3] execCommand('insertText')");

    // Trigger state update
    ['input', 'change', 'keyup', 'keydown'].forEach(type => {
        inputEl.dispatchEvent(new Event(type, { bubbles: true }));
    });
    console.log("  Triggered state update events");

    // Verify
    const value = inputEl.value || inputEl.textContent || inputEl.innerText;
    console.log(`\n[RESULT] Value length: ${value.length}`);
    console.log(`[RESULT] Content: "${value.substring(0, 50)}..."`);

    if (value.length > 10) {
        console.log("[OK] Paste thành công!");
    } else {
        console.log("[FAIL] Paste không thành công!");
    }
})();
