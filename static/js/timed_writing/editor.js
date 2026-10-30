(() => {
    "use strict";

    const root = document.getElementById(
        "timed-writing"
    );

    if (!root) {
        return;
    }

    const answer = document.getElementById(
        "writing-answer"
    );

    const clock = document.getElementById(
        "writing-clock"
    );

    const statusNode = document.getElementById(
        "writing-state"
    );

    const form = document.getElementById(
        "writing-form"
    );

    const saveButton = document.getElementById(
        "writing-save"
    );

    const finishButton = document.getElementById(
        "writing-finish"
    );

    const csrf = form.querySelector(
        "[name=csrfmiddlewaretoken]"
    ).value;

    let revision = Number(
        root.dataset.revision
    );

    let serverOffset = (
        Number(root.dataset.serverNow) * 1000
        - Date.now()
    );

    const expiresAt = (
        Number(root.dataset.expiry) * 1000
    );

    let lastSaved = answer.value;

    let busy = false;
    let closed = false;
    let fault = false;
    let lastPoll = 0;

    function state(message) {
        statusNode.textContent = message;
    }

    function disable() {
        closed = true;

        answer.readOnly = true;

        saveButton.disabled = true;
        finishButton.disabled = true;
    }

    function remaining() {
        const serverNow = (
            Date.now() + serverOffset
        );

        return Math.max(
            0,
            Math.ceil(
                (expiresAt - serverNow) / 1000
            )
        );
    }

    function tick() {
        const seconds = remaining();

        const minutes = Math.floor(
            seconds / 60
        );

        const rest = seconds % 60;

        clock.textContent = (
            String(minutes).padStart(2, "0")
            + ":"
            + String(rest).padStart(2, "0")
        );

        if (seconds === 0 && !closed) {
            disable();

            state(
                "Time expired — checking final submission..."
            );

            poll();
        }
    }

    async function poll() {
        try {
            const response = await fetch(
                root.dataset.statusUrl,
                {
                    credentials: "same-origin",
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                throw new Error(
                    "Unable to check server status"
                );
            }

            const data = await response.json();

            serverOffset = (
                data.server_now * 1000
                - Date.now()
            );

            if (data.status !== "ACTIVE") {
                disable();

                state(
                    data.status === "SUBMITTED"
                        ? "Answer submitted"
                        : "Expired without a saved answer"
                );

                if (answer.value !== data.answer) {
                    state(
                        "Session ended — check saved answer by refreshing"
                    );
                }
            }

        } catch (error) {
            state(
                "Connection error — check network"
            );
        }
    }

    async function send(action = "save") {
        if (busy || closed) {
            return false;
        }

        if (
            action === "save"
            && answer.value === lastSaved
        ) {
            return true;
        }

        busy = true;

        saveButton.disabled = true;
        finishButton.disabled = true;

        state(
            action === "finish"
                ? "Submitting..."
                : "Saving..."
        );

        const snapshot = answer.value;

        try {
            const response = await fetch(
                root.dataset.saveUrl,
                {
                    method: "POST",
                    credentials: "same-origin",
                    cache: "no-store",

                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf
                    },

                    body: JSON.stringify({
                        answer: snapshot,
                        revision: revision,
                        action: action
                    })
                }
            );

            const data = await response.json();

            if (!response.ok) {
                if (
                    response.status === 409
                    || (
                        data.status
                        && data.status !== "ACTIVE"
                    )
                ) {
                    disable();

                    state(
                        "Conflict or expired — copy your answer before refreshing"
                    );

                } else {
                    state(
                        data.error || "Could not save — retry"
                    );
                }

                fault = true;

                return false;
            }

            revision = data.revision;

            lastSaved = snapshot;
            fault = false;

            if (data.status !== "ACTIVE") {
                disable();

                state(
                    "Final answer submitted successfully"
                );

                window.location.reload();

            } else {
                state(
                    answer.value === lastSaved
                        ? "Saved"
                        : "New changes pending"
                );
            }

            return true;

        } catch (error) {
            fault = true;

            state(
                "Offline or connection error — changes NOT saved"
            );

            return false;

        } finally {
            busy = false;

            if (!closed) {
                saveButton.disabled = false;
                finishButton.disabled = false;
            }
        }
    }

    answer.addEventListener(
        "input",
        () => {
            if (!closed) {
                state("Unsaved changes");
            }
        }
    );

    form.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();

            if (!answer.value.trim()) {
                state("Type an answer first");
                return;
            }

            const confirmed = window.confirm(
                "Submit your final answer? "
                + "You cannot edit it afterward."
            );

            if (confirmed) {
                await send("finish");
            }
        }
    );

    saveButton.addEventListener(
        "click",
        () => send("save")
    );

    window.addEventListener(
        "beforeunload",
        (event) => {
            if (
                !closed
                && (
                    busy
                    || lastSaved !== answer.value
                    || fault
                )
            ) {
                event.preventDefault();
                event.returnValue = "";
            }
        }
    );

    setInterval(
        () => {
            tick();

            if (
                !closed
                && !busy
                && lastSaved !== answer.value
            ) {
                send("save");
            }

            if (
                Date.now() - lastPoll > 10000
            ) {
                lastPoll = Date.now();
                poll();
            }
        },
        4000
    );

    tick();
})();