document.addEventListener('DOMContentLoaded', function () {
    const roleField = document.querySelector('#id_role');
    const companyRow = document.querySelector('.field-company');
    const branchRow = document.querySelector('.field-branch');

    function toggleFields() {
        const role = roleField.value;

        if (role === 'company') {
            companyRow.style.display = '';
            branchRow.style.display = 'none';
        } else if (role === 'branch') {
            companyRow.style.display = 'none';
            branchRow.style.display = '';
        } else {
            companyRow.style.display = 'none';
            branchRow.style.display = 'none';
        }
    }

    roleField.addEventListener('change', toggleFields);
    toggleFields();
});
