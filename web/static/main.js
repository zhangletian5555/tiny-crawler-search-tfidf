// 保持极简：表单是服务端渲染的，这里只补两处操作细节。
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("query-input");
    if (!input) return;

    // 从结果页返回时把查询词留在输入框里，便于改词重搜
    if (!input.value) {
        const previous = new URLSearchParams(window.location.search).get("key");
        if (previous) input.value = previous;
    }

    // 聚焦时把光标放到末尾
    if (document.activeElement === input) {
        input.setSelectionRange(input.value.length, input.value.length);
    }
});
