/* منصة مدرسة أزاد الإلكترونية — سلوكيات الواجهة */
(() => {
  document.addEventListener("DOMContentLoaded", () => {
    var toggle = document.querySelector("[data-nav-toggle]");
    var links = document.querySelector("[data-nav-links]");
    if (toggle && links) {
      toggle.addEventListener("click", () => {
        var open = links.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(open));
      });
    }
    var flashes = document.querySelectorAll(".flash");
    flashes.forEach((el) => {
      setTimeout(() => {
        el.style.opacity = "0";
        el.style.transition = "opacity .4s";
        setTimeout(() => {
          el.remove();
        }, 450);
      }, 5000);
    });
  });
})();
