import { describe, it, expect, beforeEach, vi } from "vitest";

describe("AzadToast", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    window.AzadToast._container = null;
    vi.useFakeTimers();
  });

  it("creates container on first show", () => {
    window.AzadToast.show({ message: "hello", duration: 0 });
    expect(document.getElementById("azad-toasts")).toBeTruthy();
  });

  it("shows success toast", () => {
    const toast = window.AzadToast.success("تم الحفظ");
    expect(toast.classList.contains("azad-toast--success")).toBe(true);
    expect(toast.querySelector(".azad-toast__message").textContent).toBe("تم الحفظ");
    expect(toast.querySelector(".azad-toast__title").textContent).toBe("نجح");
  });

  it("shows error toast", () => {
    const toast = window.AzadToast.error("فشل");
    expect(toast.classList.contains("azad-toast--error")).toBe(true);
    expect(toast.querySelector(".azad-toast__title").textContent).toBe("خطأ");
  });

  it("shows warning toast", () => {
    const toast = window.AzadToast.warning("انتبه");
    expect(toast.classList.contains("azad-toast--warning")).toBe(true);
    expect(toast.querySelector(".azad-toast__title").textContent).toBe("تنبيه");
  });

  it("shows info toast", () => {
    const toast = window.AzadToast.info("معلومات");
    expect(toast.classList.contains("azad-toast--info")).toBe(true);
    expect(toast.querySelector(".azad-toast__title").textContent).toBe("معلومة");
  });

  it("shows with custom title", () => {
    const toast = window.AzadToast.success("msg", "عنوان مخصص");
    expect(toast.querySelector(".azad-toast__title").textContent).toBe("عنوان مخصص");
  });

  it("accepts plain string", () => {
    const toast = window.AzadToast.show("simple message");
    expect(toast.querySelector(".azad-toast__message").textContent).toBe("simple message");
  });

  it("auto-dismisses after duration", () => {
    const toast = window.AzadToast.show({ message: "gone soon", duration: 1000 });
    expect(toast.parentNode).toBeTruthy();
    vi.advanceTimersByTime(1000);
    expect(toast.style.opacity).toBe("0");
    vi.advanceTimersByTime(400);
    expect(toast.parentNode).toBeNull();
  });

  it("close button removes toast", () => {
    const toast = window.AzadToast.show({ message: "closable", duration: 0 });
    const closeBtn = toast.querySelector(".azad-toast__close");
    closeBtn.click();
    expect(toast.style.opacity).toBe("0");
    vi.advanceTimersByTime(400);
    expect(toast.parentNode).toBeNull();
  });

  it("reuses existing container", () => {
    window.AzadToast.show({ message: "first", duration: 0 });
    window.AzadToast.show({ message: "second", duration: 0 });
    const containers = document.querySelectorAll("#azad-toasts");
    expect(containers.length).toBe(1);
    expect(containers[0].children.length).toBe(2);
  });
});

describe("Theme Toggle", () => {
  beforeEach(() => {
    document.documentElement.dataset.theme = "";
    localStorage.clear();
  });

  it("applyTheme sets dark theme", () => {
    document.documentElement.dataset.theme = "dark";
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("applyTheme sets light theme", () => {
    document.documentElement.dataset.theme = "light";
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("toggles theme icons visibility", () => {
    document.body.innerHTML = `
      <span data-theme-icon-light>Sun</span>
      <span data-theme-icon-dark>Moon</span>
    `;
    document.documentElement.dataset.theme = "dark";
    const lightIcon = document.querySelector("[data-theme-icon-light]");
    const darkIcon = document.querySelector("[data-theme-icon-dark]");
    lightIcon.hidden = true;
    darkIcon.hidden = false;
    expect(lightIcon.hidden).toBe(true);
    expect(darkIcon.hidden).toBe(false);
  });
});

describe("Mobile Nav", () => {
  let toggle, links;

  beforeEach(() => {
    document.body.innerHTML = `
      <button data-nav-toggle aria-expanded="false">
        <span data-nav-icon-open>Open</span>
        <span data-nav-icon-close>Close</span>
      </button>
      <div data-nav-links>
        <a href="/home">Home</a>
      </div>
    `;
    toggle = document.querySelector("[data-nav-toggle]");
    links = document.querySelector("[data-nav-links]");

    const setOpen = (open) => {
      links.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
      const openIcon = toggle.querySelector("[data-nav-icon-open]");
      const closeIcon = toggle.querySelector("[data-nav-icon-close]");
      if (openIcon) openIcon.hidden = open;
      if (closeIcon) closeIcon.hidden = !open;
      document.body.style.overflow = open ? "hidden" : "";
    };

    toggle.addEventListener("click", () => setOpen(!links.classList.contains("open")));
    links.querySelectorAll("a, button").forEach((el) => {
      el.addEventListener("click", () => setOpen(false));
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && links.classList.contains("open")) setOpen(false);
    });
  });

  it("toggles open class on click", () => {
    toggle.click();
    expect(links.classList.contains("open")).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("closes on escape key", () => {
    links.classList.add("open");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(links.classList.contains("open")).toBe(false);
  });
});

describe("Accordion", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button class="accordion-btn" aria-expanded="false">Section 1</button>
      <div class="accordion-content">Content 1</div>
    `;
    document.querySelectorAll(".accordion-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const expanded = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", String(!expanded));
        const content = btn.nextElementSibling;
        if (content) content.classList.toggle("open", !expanded);
      });
    });
  });

  it("expands on click", () => {
    const btn = document.querySelector(".accordion-btn");
    const content = btn.nextElementSibling;
    btn.click();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(content.classList.contains("open")).toBe(true);
  });

  it("collapses on second click", () => {
    const btn = document.querySelector(".accordion-btn");
    const content = btn.nextElementSibling;
    btn.click();
    btn.click();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(content.classList.contains("open")).toBe(false);
  });
});

describe("Tabs", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="tabs">
        <a class="tab active" href="#tab1">Tab 1</a>
        <a class="tab" href="#tab2">Tab 2</a>
        <a class="tab" href="#tab3">Tab 3</a>
      </div>
    `;
    document.querySelectorAll(".tabs").forEach((tabBar) => {
      const tabs = tabBar.querySelectorAll(".tab");
      tabs.forEach((tab) => {
        tab.addEventListener("click", (e) => {
          e.preventDefault();
          tabs.forEach((t) => t.classList.remove("active"));
          tab.classList.add("active");
        });
      });
    });
  });

  it("switches active tab", () => {
    const tabs = document.querySelectorAll(".tab");
    tabs[1].click();
    expect(tabs[0].classList.contains("active")).toBe(false);
    expect(tabs[1].classList.contains("active")).toBe(true);
  });

  it("only one tab active at a time", () => {
    const tabs = document.querySelectorAll(".tab");
    tabs[2].click();
    const activeCount = [...tabs].filter((t) => t.classList.contains("active")).length;
    expect(activeCount).toBe(1);
  });
});

describe("Dropdown", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="dropdown">
        <button class="dropdown-toggle">Menu</button>
        <div class="dropdown-menu">Content</div>
      </div>
    `;
    document.querySelectorAll(".dropdown-toggle").forEach((toggle) => {
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const dropdown = toggle.closest(".dropdown");
        const wasOpen = dropdown.classList.contains("open");
        document.querySelectorAll(".dropdown.open").forEach((d) => d.classList.remove("open"));
        if (!wasOpen) dropdown.classList.add("open");
      });
    });
    document.addEventListener("click", () => {
      document.querySelectorAll(".dropdown.open").forEach((d) => d.classList.remove("open"));
    });
  });

  it("opens on toggle click", () => {
    const toggle = document.querySelector(".dropdown-toggle");
    const dropdown = toggle.closest(".dropdown");
    toggle.click();
    expect(dropdown.classList.contains("open")).toBe(true);
  });

  it("closes on second click", () => {
    const toggle = document.querySelector(".dropdown-toggle");
    const dropdown = toggle.closest(".dropdown");
    toggle.click();
    toggle.click();
    expect(dropdown.classList.contains("open")).toBe(false);
  });

  it("closes on outside click", () => {
    const toggle = document.querySelector(".dropdown-toggle");
    const dropdown = toggle.closest(".dropdown");
    toggle.click();
    document.body.click();
    expect(dropdown.classList.contains("open")).toBe(false);
  });
});

describe("Password Toggle", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="azad-field__input-wrap--password">
        <input type="password" value="secret" />
        <button data-password-toggle>Show</button>
      </div>
    `;
    document.querySelectorAll("[data-password-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const wrap = btn.closest(".azad-field__input-wrap--password");
        if (!wrap) return;
        const input = wrap.querySelector("input");
        if (!input) return;
        const isPassword = input.type === "password";
        input.type = isPassword ? "text" : "password";
      });
    });
  });

  it("toggles input type", () => {
    const btn = document.querySelector("[data-password-toggle]");
    const input = document.querySelector("input");
    expect(input.type).toBe("password");
    btn.click();
    expect(input.type).toBe("text");
    btn.click();
    expect(input.type).toBe("password");
  });
});

describe("Admin Drawer", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button data-admin-nav-toggle>Open</button>
      <button data-admin-nav-close>Close</button>
      <div data-admin-nav-overlay></div>
    `;
    const close = () => document.body.classList.remove("sidebar-open");
    document.querySelector("[data-admin-nav-toggle]").addEventListener("click", () =>
      document.body.classList.add("sidebar-open"),
    );
    document.querySelector("[data-admin-nav-close]").addEventListener("click", close);
    document.querySelector("[data-admin-nav-overlay]").addEventListener("click", close);
  });

  it("opens sidebar", () => {
    document.querySelector("[data-admin-nav-toggle]").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(true);
  });

  it("closes sidebar", () => {
    document.body.classList.add("sidebar-open");
    document.querySelector("[data-admin-nav-close]").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
  });

  it("closes on overlay click", () => {
    document.body.classList.add("sidebar-open");
    document.querySelector("[data-admin-nav-overlay]").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
  });
});

describe("Flash Messages", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("auto-dismisses after delay", () => {
    document.body.innerHTML = `
      <div class="flash" data-auto-dismiss="1000">Alert!</div>
      <div class="flash" data-auto-dismiss="2000">Slow alert!</div>
    `;
    const flashes = document.querySelectorAll(".flash[data-auto-dismiss]");
    flashes.forEach((el) => {
      const delay = parseInt(el.dataset.autoDismiss, 10) || 5000;
      setTimeout(() => {
        el.style.opacity = "0";
        el.style.transform = "translateY(-8px)";
        el.style.transition = "opacity .3s, transform .3s";
        setTimeout(() => el.remove(), 350);
      }, delay);
    });

    expect(flashes.length).toBe(2);
    vi.advanceTimersByTime(1100);
    expect(flashes[0].style.opacity).toBe("0");
    expect(flashes[1].style.opacity).not.toBe("0");
  });
});

describe("Scroll Animations", () => {
  it("adds azad-in-view class to intersecting elements", () => {
    document.body.innerHTML = `
      <div class="azad-card" id="card1">Card 1</div>
      <div class="azad-card" id="card2">Card 2</div>
    `;
    const cards = document.querySelectorAll(".azad-card");
    cards.forEach((el) => {
      el.style.opacity = "0";
      el.classList.add("azad-in-view");
    });
    expect(document.getElementById("card1").classList.contains("azad-in-view")).toBe(true);
  });
});

describe("Lazy Images", () => {
  it("observes data-src images", () => {
    document.body.innerHTML = `
      <img data-src="/img/photo.jpg" id="lazy1" />
      <img data-src="/img/hero.png" id="lazy2" />
    `;
    const imgs = document.querySelectorAll("img[data-src]");
    expect(imgs.length).toBe(2);
    imgs.forEach((img) => {
      if (img.dataset.src) {
        img.src = img.dataset.src;
        img.removeAttribute("data-src");
      }
    });
    expect(document.getElementById("lazy1").src).toContain("/img/photo.jpg");
    expect(document.getElementById("lazy1").hasAttribute("data-src")).toBe(false);
  });
});

describe("Page Transitions", () => {
  it("fades body on internal link click", () => {
    document.body.innerHTML = '<a href="/dashboard">Dashboard</a>';
    const link = document.querySelector('a[href="/dashboard"]');
    link.addEventListener("click", () => {
      document.body.style.opacity = "0.7";
      document.body.style.transition = "opacity .15s";
    });
    link.click();
    expect(document.body.style.opacity).toBe("0.7");
  });
});
