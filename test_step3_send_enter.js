// STEP 3: Gửi prompt bằng Enter
// Paste vào Console (F12) sau khi đã paste prompt

(function() {
    console.log("=== STEP 3: Gửi prompt bằng Enter ===");

    // Tìm input field đang focus
    let inputEl = document.activeElement;

    // Nếu không có active element phù hợp, tìm lại
    if (!inputEl || inputEl === document.body) {
        const selectors = ['textarea', 'div[contenteditable="true"]', '[role="textbox"]'];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
                inputEl = el;
                inputEl.focus();
                break;
            }
        }
    }

    console.log(`Input element: ${inputEl?.tagName || 'none'}`);

    // Gửi Enter event
    console.log("Sending Enter key...");

    const enterEvent = new KeyboardEvent('keydown', {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true,
        cancelable: true
    });
    inputEl.dispatchEvent(enterEvent);
    console.log("  [1] Dispatched keydown Enter");

    const enterPress = new KeyboardEvent('keypress', {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true
    });
    inputEl.dispatchEvent(enterPress);
    console.log("  [2] Dispatched keypress Enter");

    const enterUp = new KeyboardEvent('keyup', {
        key: 'Enter',
        code: 'Enter',
        keyCode: 13,
        which: 13,
        bubbles: true
    });
    inputEl.dispatchEvent(enterUp);
    console.log("  [3] Dispatched keyup Enter");

    console.log("\n[DONE] Đã gửi Enter - Kiểm tra xem request có được gửi không");
})();
