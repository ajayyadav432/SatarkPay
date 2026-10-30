// One login page for the three kinds of account. The server checks the password and sets a cookie scripts cannot read.
(function () {
  const { sendJSON, topbar } = SP;
  const $ = (id) => document.getElementById(id);
  const NOTES = {
    user: "Check a payment before you pay.",
    merchant: "See what really reached your shop.",
    admin: "Watch every payment, review alerts and run the simulation.",
  };
  let role = "user";

  function pick(next) {
    role = next;
    document.querySelectorAll(".login-role").forEach((b) => {
      const on = b.dataset.role === role;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    $("role-note").textContent = NOTES[role];
    $("login-error").classList.add("hidden");
  }

  $("top").replaceWith(topbar("/login"));
  document.querySelectorAll(".login-role").forEach((b) => b.addEventListener("click", () => pick(b.dataset.role)));
  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("btn-login").disabled = true;
    try {
      const me = await sendJSON("/api/v1/auth/login", { role, username: $("username").value, password: $("password").value });
      location.href = me.home;
    } catch (err) {
      $("login-error").textContent = err.message;
      $("login-error").classList.remove("hidden");
      $("btn-login").disabled = false;
    }
  });
  pick("user");
})();
