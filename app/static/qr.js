// Fake payment requests for the phone app to scan, so a scam can be caught live in front of people.
(function () {
  const { h, topbar } = SP;
  const CODES = [
    ["shop", "A local shop", "Should go through"],
    ["qr", "\"Scan to receive\"", "Should be stopped: scanning only ever sends money"],
    ["fake_collect", "A fake refund", "Should be stopped: a bank never refunds this way"],
    ["mule", "A job \"deposit\"", "Should raise a warning or be stopped"],
    ["phishing", "A QR with a fake bank link", "Not a payment: the app checks the page instead"],
  ];
  document.getElementById("top").replaceWith(topbar("/qr"));
  document.getElementById("codes").replaceChildren(...CODES.map(([id, title, expect]) =>
    h("section", { class: "card", "data-qr": id },
      h("h2", { text: title }),
      h("img", { src: `/api/v1/demo/qr/${id}.svg`, alt: `QR code: ${title}`, width: "280", height: "280" }),
      h("p", { class: "small muted", text: expect }))));
})();
