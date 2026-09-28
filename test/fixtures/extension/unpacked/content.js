// Runs only when the browser really loaded this unpacked extension
// (--load-extension). The page can read the mark: the DOM is shared.
document.documentElement.dataset.cdpilotExt = 'loaded:' + chrome.runtime.id;
