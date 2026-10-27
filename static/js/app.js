document.addEventListener("DOMContentLoaded", () => {
    console.log("AssignHub frontend initialized.");
});

/* =====================================
   ASSIGNHUB DASHBOARD JAVASCRIPT
   ===================================== */

document.addEventListener("DOMContentLoaded", function () {

    const dashboard = document.querySelector(".ah-dashboard");

    if (!dashboard) {
        return;
    }

    /* ---------------------------------
       1. INITIALIZE LUCIDE ICONS
       --------------------------------- */

    if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons({
            attrs: {
                "stroke-width": 1.8
            }
        });
    }

    /* ---------------------------------
       2. ENTRANCE ANIMATIONS
       --------------------------------- */

    const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
    ).matches;

    if (!reduceMotion) {
        dashboard.classList.add("ah-animate-ready");
    }

    /* ---------------------------------
       3. WELCOME HAND ANIMATION
       --------------------------------- */

    const wave = dashboard.querySelector(".ah-wave");

    if (wave && !reduceMotion) {
        wave.classList.add("animate");

        wave.addEventListener(
            "animationend",
            function () {
                wave.classList.remove("animate");
            },
            { once: true }
        );
    }

    /* ---------------------------------
       4. CARD HOVER MICRO INTERACTIONS
       --------------------------------- */

    const cards = dashboard.querySelectorAll(".ah-feature-card");

    cards.forEach(function (card) {

        card.addEventListener("mouseenter", function () {
            card.classList.add("ah-card-hovered");
        });

        card.addEventListener("mouseleave", function () {
            card.classList.remove("ah-card-hovered");
        });

    });

});
