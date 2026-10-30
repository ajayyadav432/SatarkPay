// One page for the three portals: log in, sign up (user and merchant) or one-click test login.
(function () {
  const { sendJSON, getJSON, topbar } = SP;
  const $ = (id) => document.getElementById(id);
  const NOTES = {
    user: "Check a payment before you pay.",
    merchant: "See what really reached your shop.",
    admin: "Watch every payment, review alerts and run the simulation.",
  };
  const LABEL = { user: "User", merchant: "Merchant", admin: "Admin" };
  let role = "user";
  let signingUp = false;
  let canTest = false;

  function paint() {
    if (role === "admin") signingUp = false;
    document.querySelectorAll(".login-role").forEach((b) => {
      const on = b.dataset.role === role;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    $("role-note").textContent = NOTES[role];
    $("login-error").classList.add("hidden");
    $("test-box").classList.toggle("hidden", !canTest);
    $("btn-test").textContent = `Use test login: ${LABEL[role]}`;
    $("name-box").classList.toggle("hidden", !signingUp);
    $("fullname").required = signingUp;
    $("name-label").textContent = role === "merchant" ? "Shop name" : "Your name";
    $("password").autocomplete = signingUp ? "new-password" : "current-password";
    $("btn-login").textContent = signingUp ? "Sign up" : "Log in";
    $("switch-text").textContent = role === "admin" ? "Admin accounts cannot be created here." : signingUp ? "Already have an account?" : "New here?";
    $("btn-switch").classList.toggle("hidden", role === "admin");
    $("btn-switch").textContent = signingUp ? "Log in" : "Sign up";
  }

  async function go(url, body, button) {
    button.disabled = true;
    try {
      location.href = (await sendJSON(url, body)).home;
    } catch (err) {
      $("login-error").textContent = err.message;
      $("login-error").classList.remove("hidden");
      button.disabled = false;
    }
  }

  $("top").replaceWith(topbar("/login"));
  document.querySelectorAll(".login-role").forEach((b) => b.addEventListener("click", () => { role = b.dataset.role; paint(); }));
  $("btn-switch").addEventListener("click", () => { signingUp = !signingUp; paint(); });
  $("btn-test").addEventListener("click", () => go("/api/v1/auth/test-login", { role }, $("btn-test")));
  $("login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const body = { role, username: $("username").value, password: $("password").value };
    if (signingUp) go("/api/v1/auth/signup", { ...body, name: $("fullname").value }, $("btn-login"));
    else go("/api/v1/auth/login", body, $("btn-login"));
  });
  paint();
  getJSON("/api/v1/auth/options").then((o) => { canTest = o.test_logins; paint(); }).catch(() => {});
})();
