/* apps/tenant/branch/static/branch/js/ai_reply.js */
$(document).ready(function () {
    console.log("AI Reply script loaded.");

    $('#generate-ai-btn').click(function () {
        console.log("Generate AI button clicked.");
        var btn = $(this);
        var loading = $('#ai-loading');
        var error = $('#ai-error');
        var textarea = $('#id_text'); // Django default ID for charfield widget

        // Get review data (from the first item, assuming single reply for best context)
        var reviewData = $('.review-data').first();
        var reviewText = reviewData.data('text') || "";
        var reviewRating = reviewData.data('rating') || 5;
        var draftText = textarea.val();

        btn.prop('disabled', true);
        loading.show();
        error.text('');

        // Get CSRF token
        var csrfToken = $('[name=csrfmiddlewaretoken]').val();

        $.ajax({
            url: '/admin-tools/generate-reply/',
            type: 'POST',
            contentType: 'application/json',
            headers: { 'X-CSRFToken': csrfToken },
            data: JSON.stringify({
                review_text: reviewText,
                review_rating: reviewRating,
                draft_text: draftText
            }),
            success: function (response) {
                console.log("AI Response:", response);
                if (response.reply) {
                    textarea.val(response.reply);
                } else if (response.error) {
                    error.text('Ошибка: ' + response.error);
                }
            },
            error: function (xhr) {
                console.error("AI Error:", xhr);
                var msg = 'Неизвестная ошибка';
                if (xhr.responseJSON && xhr.responseJSON.error) {
                    msg = xhr.responseJSON.error;
                }
                error.text('Ошибка: ' + msg);
            },
            complete: function () {
                btn.prop('disabled', false);
                loading.hide();
            }
        });
    });
});
