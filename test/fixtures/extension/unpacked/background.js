// A service worker, so the extension shows up as a CDP target
// (chrome-extension://<id>/background.js) as well.
chrome.runtime.onInstalled.addListener(() => {});
