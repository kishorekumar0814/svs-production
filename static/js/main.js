const navToggle = document.getElementById("navToggle");
const sideNav = document.getElementById("sideNav");

if (navToggle && sideNav) {
  navToggle.addEventListener("click", () => {
    const isMobile = window.matchMedia("(max-width: 700px)").matches;
    if (isMobile) {
      sideNav.classList.toggle("open");
      return;
    }
    sideNav.classList.toggle("collapsed");
  });
}

function cardPop(el){
  el.classList.add("pop");
  setTimeout(() => el.classList.remove("pop"), 400);
}

const offlinePath = "/offline";

function redirectIfOffline() {
  if (!navigator.onLine && window.location.pathname !== offlinePath) {
    window.location.href = offlinePath;
  }
}

window.addEventListener("offline", redirectIfOffline);

