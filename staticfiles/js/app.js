
/* =====================================
   ASSIGNHUB FRONTEND INITIALIZATION
   ===================================== */

document.addEventListener("DOMContentLoaded", () => {
    console.log("AssignHub frontend initialized.");
});


/* =====================================
   ASSIGNHUB DASHBOARD JAVASCRIPT
   ===================================== */

document.addEventListener("DOMContentLoaded", function () {

    // Support both existing dashboard class names
    const dashboards = document.querySelectorAll(
        ".ah-dashboard, .ah-dash"
    );

    if (!dashboards.length) {
        return;
    }

    /* ---------------------------------
       1. INITIALIZE LUCIDE ICONS
       --------------------------------- */

    if (
        window.lucide &&
        typeof window.lucide.createIcons === "function"
    ) {
        window.lucide.createIcons({
            attrs: {
                "stroke-width": 1.8
            }
        });
    }

    /* ---------------------------------
       2. CHECK REDUCED MOTION
       --------------------------------- */

    const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
    ).matches;


    dashboards.forEach(function (dashboard) {

        /* ---------------------------------
           3. INITIAL PAGE-LOAD ANIMATIONS
           --------------------------------- */

        if (!reduceMotion) {

            requestAnimationFrame(function () {

                dashboard.classList.add("ah-animate-ready");

            });

        }


        /* ---------------------------------
           4. WELCOME HAND ANIMATION
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
           5. CARD HOVER MICRO INTERACTIONS
           EXISTING FUNCTIONALITY PRESERVED
           --------------------------------- */

        const cards = dashboard.querySelectorAll(
            ".ah-feature-card"
        );

        cards.forEach(function (card) {

            card.addEventListener("mouseenter", function () {

                card.classList.add("ah-card-hovered");

            });

            card.addEventListener("mouseleave", function () {

                card.classList.remove("ah-card-hovered");

            });

        });

    });

});
