// STEP 1: Chọn mode "Tạo hình ảnh"
// Paste vào Console (F12) sau khi mở https://labs.google/fx/vi/tools/flow

(function() {
    console.log("=== STEP 1: Chọn mode Tạo hình ảnh ===");

    // Tìm tất cả buttons/tabs
    const allButtons = document.querySelectorAll('button, [role="tab"], [role="button"]');
    console.log(`Tìm thấy ${allButtons.length} buttons/tabs`);

    let found = false;
    allButtons.forEach((btn, i) => {
        const text = (btn.textContent || btn.innerText || '').trim();
        const ariaLabel = btn.getAttribute('aria-label') || '';

        // Tìm button có chứa "hình ảnh" hoặc "image"
        if (text.toLowerCase().includes('hình ảnh') ||
            text.toLowerCase().includes('image') ||
            ariaLabel.toLowerCase().includes('hình ảnh') ||
            ariaLabel.toLowerCase().includes('image')) {
            console.log(`[${i}] FOUND: "${text}" | aria="${ariaLabel}"`);
            console.log("  -> Clicking...");
            btn.click();
            found = true;
        }
    });

    if (!found) {
        console.log("Không tìm thấy button 'Tạo hình ảnh'");
        console.log("Liệt kê 20 buttons đầu tiên:");
        Array.from(allButtons).slice(0, 20).forEach((btn, i) => {
            const text = (btn.textContent || '').trim().substring(0, 50);
            console.log(`  [${i}] "${text}"`);
        });
    } else {
        console.log("[OK] Đã click chọn mode Tạo hình ảnh");
    }
})();
