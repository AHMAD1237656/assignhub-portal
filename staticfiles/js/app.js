
/* ==========================================
   ASSIGNHUB FRONTEND INITIALIZATION
   Unified Dashboard JavaScript
========================================== */

(function () {

    "use strict";


    /* =====================================
       1. FRONTEND INITIALIZATION
    ===================================== */

    function initializeAssignHub() {

        console.log("AssignHub frontend initialized.");


        /* =====================================
           2. INITIALIZE LUCIDE ICONS
        ===================================== */

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

/* =====================================
   ASSIGNHUB LOGIN PAGE INITIALIZATION
===================================== */

const loginPage = document.querySelector(".ah-login-page");

if (loginPage && !reduceMotion) {

    window.requestAnimationFrame(function () {

        loginPage.classList.add("ah-login-animate-ready");

    });

}


        /* =====================================
           3. FIND ALL DASHBOARDS
           Supports both dashboard classes
        ===================================== */

        const dashboards = document.querySelectorAll(
            ".ah-dashboard, .ah-dash"
        );

        if (!dashboards.length) {
            return;
        }


        /* =====================================
           4. ACCESSIBILITY: REDUCED MOTION
        ===================================== */

        const reduceMotion = window.matchMedia &&
            window.matchMedia(
                "(prefers-reduced-motion: reduce)"
            ).matches;


        /* =====================================
           5. INITIALIZE EACH DASHBOARD
        ===================================== */

        dashboards.forEach(function (dashboard) {


            /* ---------------------------------
               Prevent duplicate initialization
            --------------------------------- */

            if (dashboard.dataset.ahInitialized === "true") {
                return;
            }

            dashboard.dataset.ahInitialized = "true";


            /* =================================
               6. INITIAL PAGE-LOAD ANIMATIONS
               Runs only once on page load
            ================================= */

            if (!reduceMotion) {

                window.requestAnimationFrame(function () {

                    dashboard.classList.add(
                        "ah-animate-ready"
                    );

                });

            }


            /* =================================
               7. WELCOME HAND ANIMATION
               Existing functionality preserved
            ================================= */

            const wave = dashboard.querySelector(
                ".ah-wave"
            );

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


            /* =================================
               8. CARD HOVER MICRO INTERACTIONS
               Existing functionality preserved
            ================================= */

            const cards = dashboard.querySelectorAll(
                ".ah-feature-card"
            );

            cards.forEach(function (card) {

                card.addEventListener(
                    "mouseenter",
                    function () {

                        card.classList.add(
                            "ah-card-hovered"
                        );

                    }
                );

                card.addEventListener(
                    "mouseleave",
                    function () {

                        card.classList.remove(
                            "ah-card-hovered"
                        );

                    }
                );

            });


        });


    }


    /* =====================================
       9. DOM READY HANDLING
       Supports deferred and normal scripts
    ===================================== */

    if (document.readyState === "loading") {

        document.addEventListener(
            "DOMContentLoaded",
            initializeAssignHub,
            { once: true }
        );

    } else {

        initializeAssignHub();

    }


})();
