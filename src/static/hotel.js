// ── Navbar toggler ──────────────────────────────────────────────────────────
// Runs only when the toggler button exists (layout.html always has it)
document.addEventListener('DOMContentLoaded', function () {
    const toggler_button = document.querySelector('.navbar-toggler');
    const drop_down      = document.querySelector('.collapse');
    const button_icon    = document.querySelector('.navbar-toggler-icon');

    if (toggler_button && drop_down && button_icon) {
        toggler_button.onclick = function () {
            drop_down.classList.toggle('open');
            const isOpen = drop_down.classList.contains('open');
            button_icon.className = isOpen
                ? 'fa-solid fa-xmark'
                : 'fa-solid fa-bars';
        };
    }
});

// ── Children age selects (search form) ──────────────────────────────────────
$(function toggle_display() {
    $('option').click(function () {
        const one_child    = document.querySelector('.one_child');
        const two_children = document.querySelector('.two_children');
        if (!one_child || !two_children) return;

        const total_children = $(this).val();

        if (total_children === 'one') {
            one_child.style.display    = 'block';
            two_children.style.display = 'none';
            $('.required1').prop('required', true);
            $('.required2').prop('required', false);
        } else if (total_children === 'two') {
            one_child.style.display    = 'block';
            two_children.style.display = 'block';
            $('.required1').prop('required', true);
            $('.required2').prop('required', true);
        } else {
            one_child.style.display    = 'none';
            two_children.style.display = 'none';
            $('.required1').prop('required', false);
            $('.required2').prop('required', false);
        }
    });

    // ── Rate plan period show/hide ───────────────────────────────────────────
    let val = 0;
    $(document).on('click', '#add_rate_plan, #remove_rate_plan', function () {
        const period_2 = document.querySelector('.period_two');
        const period_3 = document.querySelector('.period_three');
        const period_4 = document.querySelector('.period_four');
        if (!period_2) return;

        const on_button_click = $(this).val();
        if (on_button_click === 'add') {
            val = Math.min(val + 1, 3);
        } else if (on_button_click === 'remove') {
            val = Math.max(val - 1, 0);
        }

        period_2.style.display = val >= 1 ? 'block' : 'none';
        period_3.style.display = val >= 2 ? 'block' : 'none';
        period_4.style.display = val >= 3 ? 'block' : 'none';

        $('.requered_rate_plan2').prop('required', val >= 1);
        $('.requered_rate_plan3').prop('required', val >= 2);
        $('.requered_rate_plan4').prop('required', val >= 3);
    });
});

// ── Rate plan row toggles ────────────────────────────────────────────────────
[1, 2, 3, 4, 5].forEach(function (n) {
    $(document).ready(function () {
        $(`#show${n}, #hide${n}`).on('click', function () {
            $(`.hide_row${n}`).toggle();
        });
    });
});

// ── Date pickers (search form) ───────────────────────────────────────────────
$(function () {
    if ($('.dates #checkin').length) {
        $('.dates #checkin').datepicker({
            format: 'dd-mm-yyyy', todayHighlight: true,
            showOnFocus: true, startDate: '0', autoclose: true
        });
    }
    if ($('.dates #checkout').length) {
        $('.dates #checkout').datepicker({
            format: 'dd-mm-yyyy', todayHighlight: true,
            showOnFocus: true, startDate: '0', autoclose: true
        });
    }
});

// ── Date pickers (rate plan / availability forms) ────────────────────────────
$(function () {
    const ratePlanIds = [
        '#from_date', '#to_date',
        '#start_date', '#end_date',
        '#start_date_1', '#end_date_1',
        '#start_date_2', '#end_date_2',
        '#start_date_3', '#end_date_3',
        '#start_date_4', '#end_date_4',
    ];
    ratePlanIds.forEach(function (id) {
        if ($(id).length) {
            $(id).datepicker({
                format: 'dd-mm-yyyy', todayHighlight: true,
                showOnFocus: true, startDate: '0', autoclose: true
            });
        }
    });
});

// ── DataTables ───────────────────────────────────────────────────────────────
// FIX #19: guard with existence check — previously threw errors on every page
// that doesn't have these tables.
$(document).ready(function () {
    if ($('#reservations_table').length) {
        $('#reservations_table').DataTable();
    }
    if ($('#example').length) {
        $('#example').DataTable();
    }
});