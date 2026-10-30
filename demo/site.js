// Says on the page whether the SatarkPay app can be reached, as the extension needs it.
fetch("http://127.0.0.1:8000/api/health", { mode: "no-cors" }).then(function () {
  document.getElementById("ready").textContent = "SatarkPay is running. Load the extension from the extension folder, then reload this page.";
}).catch(function () {
  document.getElementById("ready").textContent = "SatarkPay is not running. Start ./run.sh first, then reload this page.";
});
