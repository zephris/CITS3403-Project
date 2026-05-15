document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("search-input");
    const searchButton = document.getElementById("search-btn");

    if (searchInput && searchButton) {
        searchButton.addEventListener("click", function () {
            // The form submits to Flask, so no extra JavaScript is required here.
        });
    }
});
