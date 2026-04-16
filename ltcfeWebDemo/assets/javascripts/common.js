// ========== 網路狀態模擬功能 ==========
let isOnline = true;
let networkStatusTimer = null;

// 更新網路狀態 UI
function updateNetworkStatus(online) {
    const statusIndicator = document.getElementById('netStatusIndicator');
    const statusBar = document.getElementById('networkStatusBar');
    const statusText = document.getElementById('networkStatusText');

    if (online) {
        statusBar.classList.remove('offline');
        statusBar.classList.add('online');
        statusIndicator.classList.remove('offline');
        statusIndicator.classList.add('online');
        // statusText.textContent = '網路服務中';
    } else {
        statusBar.classList.remove('online');
        statusBar.classList.add('offline');
        statusIndicator.classList.remove('online');
        statusIndicator.classList.add('offline');
        // statusText.textContent = '目前無網路服務(請勿關閉此瀏覽器APP)';
    }
}

// 切換網路狀態（示意用，每5秒切換一次）
function startNetworkStatusDemo() {
    networkStatusTimer = setInterval(() => {
        isOnline = !isOnline;
        updateNetworkStatus(isOnline);
    }, 5000);
}

// 初始化網路狀態
updateNetworkStatus(isOnline);
// startNetworkStatusDemo();

// ========== Notyf 通知功能 ==========
document.addEventListener('DOMContentLoaded', function () {
    // 初始化 Notyf，設定顯示位置為上方中央
    const notyf = new Notyf({
        position: {
            x: 'center',
            y: 'top',
        },
        duration: 30000, // 訊息停留 3 秒
        dismissible: true
    });

    // 暫存按鈕事件
    const saveBtn = document.querySelector('.nav-item[title="暫存"]');
    if (saveBtn) {
        saveBtn.addEventListener('click', function () {
            notyf.success('評鑑資料已暫存');
        });
    }

    // 送出按鈕事件
    const submitBtn = document.querySelector('.nav-item[title="送出"]');
    if (submitBtn) {
        submitBtn.addEventListener('click', function () {
            notyf.success('評鑑資料已送出');
        });
    }
});
