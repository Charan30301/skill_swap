document.addEventListener(
    "DOMContentLoaded",
    function () {

        console.log(
            "Skill Swap JavaScript loaded successfully!"
        );


        /* Delete confirmation */

        const deleteButtons =
            document.querySelectorAll(
                ".delete-confirm"
            );


        deleteButtons.forEach(
            function (button) {

                button.addEventListener(
                    "click",
                    function (event) {

                        const result =
                            confirm(
                                "Are you sure you want to delete this?"
                            );


                        if (!result) {

                            event.preventDefault();

                        }

                    }
                );

            }
        );


        /* Flash message */

        const messages =
            document.querySelectorAll(
                ".flash"
            );


        messages.forEach(
            function (message) {

                setTimeout(
                    function () {

                        message.style.transition =
                            "opacity 0.5s";

                        message.style.opacity =
                            "0";


                        setTimeout(
                            function () {

                                message.remove();

                            },
                            500
                        );

                    },
                    4000
                );

            }
        );


        /* Automatically scroll chat */

        const chat =
            document.getElementById(
                "messages"
            );


        if (chat) {

            chat.scrollTop =
                chat.scrollHeight;

        }

    }
);

