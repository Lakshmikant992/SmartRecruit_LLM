const body = document.querySelector("body"),
      modeToggle = body.querySelector(".mode-toggle"),
      sidebar = body.querySelector("nav"),
      sidebarToggle = body.querySelector(".sidebar-toggle"),
      navScrim = body.querySelector(".nav-scrim");

let getMode = localStorage.getItem("mode");
if(getMode && getMode ==="dark"){
    body.classList.toggle("dark");
}

let getStatus = localStorage.getItem("status");
if(getStatus && getStatus ==="close"){
    sidebar.classList.toggle("close");
}

modeToggle?.addEventListener("click", () =>{
    body.classList.toggle("dark");
    if(body.classList.contains("dark")){
        localStorage.setItem("mode", "dark");
    }else{
        localStorage.setItem("mode", "light");
    }
});

sidebarToggle?.addEventListener("click", () => {
    if (window.matchMedia("(max-width: 650px)").matches) {
        sidebar.classList.toggle("mobile-open");
        navScrim?.classList.toggle("visible");
        return;
    }
    sidebar.classList.toggle("close");
    if(sidebar.classList.contains("close")){
        localStorage.setItem("status", "close");
    }else{
        localStorage.setItem("status", "open");
    }
})
navScrim?.addEventListener("click", () => {
    sidebar.classList.remove("mobile-open");
    navScrim.classList.remove("visible");
});
document.querySelectorAll("nav a").forEach(link => link.addEventListener("click", () => {
    sidebar.classList.remove("mobile-open");
    navScrim?.classList.remove("visible");
}));