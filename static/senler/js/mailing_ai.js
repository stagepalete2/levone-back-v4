/* apps/tenant/senler/static/senler/js/mailing_ai.js */
$(document).ready(function () {
    console.log("Mailing AI script loaded.");

    // Найдем поле текста (id_text)
    var textField = $('#id_text');
    if (textField.length > 0) {
        // Создадим кнопку
        var btn = $('<button type="button" class="button" style="background-color: #264b5d; color: white; display: inline-block; margin-left: 10px;">✨ AI Generate</button>');
        var loading = $('<span style="display:none; margin-left: 10px; color: #666;">Generating...</span>');

        // Вставим кнопку после label или самого поля. 
        // В Django Admin поля находятся в div.form-row
        // Лучше вставить над полем или рядом с label.
        // Попробуем вставить прямо перед textarea (или после label)
        var wrapper = textField.closest('.form-row');
        var label = wrapper.find('label').first();

        label.after(loading);
        label.after(btn);

        btn.click(function () {
            var topic = textField.val();
            if (!topic) {
                alert("Напишите тему рассылки или набросок в поле текста, чтобы AI мог его улучшить.");
                return;
            }

            btn.prop('disabled', true);
            loading.show();

            var csrfToken = $('[name=csrfmiddlewaretoken]').val();

            $.ajax({
                url: '/admin-tools/generate-mailing/',
                type: 'POST',
                contentType: 'application/json',
                headers: { 'X-CSRFToken': csrfToken },
                data: JSON.stringify({
                    topic: topic
                }),
                success: function (response) {
                    if (response.text) {
                        textField.val(response.text);
                    } else if (response.error) {
                        alert("Error: " + response.error);
                    }
                },
                error: function (xhr) {
                    alert("Error communicating with AI.");
                    console.error(xhr);
                },
                complete: function () {
                    btn.prop('disabled', false);
                    loading.hide();
                }
            });
        });
    }
});
