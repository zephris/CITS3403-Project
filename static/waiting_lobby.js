document.getElementById("back-btn").addEventListener("click", function () {
    alert("Back button clicked");
});

document.getElementById("logout-btn").addEventListener("click", function () {
    alert("Logout button clicked");
});

document.getElementById("ready-btn").addEventListener("click", function () {
    const readyButton = document.getElementById("ready-btn");
    const playerReadyStatus = document.getElementById("player-2-ready-status");
    const lobbyStatus = document.getElementById("lobby-status");

    if (readyButton.textContent.trim() === "Ready") {
        readyButton.textContent = "Unready";
        readyButton.classList.remove("btn-success");
        readyButton.classList.add("btn-warning");

        playerReadyStatus.textContent = "Ready";
        playerReadyStatus.classList.remove("text-danger");
        playerReadyStatus.classList.add("text-success");

        lobbyStatus.textContent = "All players are ready.";
    } else {
        readyButton.textContent = "Ready";
        readyButton.classList.remove("btn-warning");
        readyButton.classList.add("btn-success");

        playerReadyStatus.textContent = "Not Ready";
        playerReadyStatus.classList.remove("text-success");
        playerReadyStatus.classList.add("text-danger");

        lobbyStatus.textContent = "Waiting for players...";
    }
});

document.getElementById("leave-lobby-btn").addEventListener("click", function () {
    alert("Leave Lobby button clicked");
});

document.getElementById("start-game-btn").addEventListener("click", function () {
    const lobbyStatus = document.getElementById("lobby-status");

    if (lobbyStatus.textContent === "All players are ready.") {
        alert("Starting game...");
    } else {
        alert("Cannot start game yet. All players must be ready.");
    }
});