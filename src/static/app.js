document.addEventListener("submit", function (event) {
  var form = event.target;
  var question = form.getAttribute("data-confirm");
  if (question && !window.confirm(question)) {
    event.preventDefault();
    return;
  }
  var busy = form.getAttribute("data-busy");
  if (busy) {
    var button = form.querySelector("button[type=submit]");
    if (button) {
      button.disabled = true;
      button.textContent = "Working...";
    }
    var message = form.querySelector(".busy-message");
    if (message) {
      message.textContent = busy;
    }
  }
});
