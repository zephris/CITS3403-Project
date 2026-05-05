document.getElementById("back-btn").addEventListener("click", function () {
    alert("Back button clicked");
});

document.getElementById("logout-btn").addEventListener("click", function () {
    alert("Logout button clicked");
});

document.getElementById("search-btn").addEventListener("click", function () {
    const searchText = document.getElementById("search-input").value.toLowerCase();
    const rows = document.querySelectorAll("#lobby-list tr");

    rows.forEach(function (row) {
        const roomName = row.children[0].textContent.toLowerCase();
        const hostName = row.children[1].textContent.toLowerCase();

        if (roomName.includes(searchText) || hostName.includes(searchText)) {
            row.style.display = "";
        } else {
            row.style.display = "none";
        }
    });
});

document.getElementById("create-lobby-btn").addEventListener("click", function () {
    alert("Create Lobby button clicked");
});

document.getElementById("quick-join-btn").addEventListener("click", function () {
    alert("Quick Join button clicked");
});

const joinButtons = document.querySelectorAll(".join-btn");

joinButtons.forEach(function (button) {
    button.addEventListener("click", function () {
        const row = button.closest("tr");
        const roomName = row.children[0].textContent;

        alert("Joining lobby: " + roomName);
    });
});