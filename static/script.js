
const form = document.getElementById("expense-form");
const subjectInput = document.getElementById("subject");
const priceInput = document.getElementById("price");
const message = document.getElementById("form-message");
const addButton = document.getElementById("add-button");

const money = amount =>
    new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2
    }).format(amount);

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        credentials: "same-origin"
    });

    const data = await response.json();

    if (response.status === 401) {
        window.location.href = "/login";
        throw new Error("Please log in again.");
    }

    if (!response.ok) {
        throw new Error(data.error || "Something went wrong.");
    }

    return data;
}

function showMessage(text, isError = false) {
    if (!message) return;
    message.textContent = text;
    message.style.color = isError ? "#FFB4AB" : "#06D6A0";
}

async function loadExpenses() {
    const expenses = await fetchJSON("/api/expenses");
    const list = document.getElementById("expense-list");
    const today = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Kolkata",
        year: "numeric",
        month: "2-digit",
        day: "2-digit"
    }).format(new Date());

    let todayTotal = 0;
    let todayCount = 0;
    list.replaceChildren();

    if (expenses.length === 0) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "No expenses yet. Add your first expense!";
        list.appendChild(empty);
    }

    expenses.forEach(expense => {
        if (expense.expense_date === today) {
            todayTotal += expense.price;
            todayCount++;
        }

        const item = document.createElement("div");
        item.className = "expense-item";

        const details = document.createElement("div");
        const name = document.createElement("h3");
        const dateTime = document.createElement("p");
        const amount = document.createElement("strong");

        name.textContent = expense.subject;

        const [hours, minutes] = expense.expense_time.split(":");
        const time = new Date();
        time.setHours(Number(hours), Number(minutes), 0, 0);

        const normalTime = time.toLocaleTimeString("en-IN", {
            hour: "numeric",
            minute: "2-digit",
            hour12: true
        });

        dateTime.textContent = `${expense.expense_date} · ${normalTime}`;
        amount.textContent = money(expense.price);

        details.append(name, dateTime);
        item.append(details, amount);
        list.appendChild(item);
    });

    document.getElementById("today-total").textContent = money(todayTotal);
    document.getElementById("expense-count").textContent =
        `${todayCount} expense${todayCount === 1 ? "" : "s"} today`;
}

async function loadMonthlyReport() {
    const report = await fetchJSON("/api/monthly-report");

    document.getElementById("report-month").textContent = report.month;
    document.getElementById("month-total").textContent = money(report.total);
    document.getElementById("month-count").textContent = report.count;
    document.getElementById("daily-average").textContent =
        money(report.daily_average);
    document.getElementById("highest-day").textContent =
        report.highest_day || "—";

    renderChart(report);
}

function renderChart(report) {
    const chart = document.getElementById("chart-bars");
    chart.replaceChildren();

   const [month, year] = report.month.split(" ");
    const monthIndex = new Date(`${month} 1, ${year}`).getMonth();
    const daysInMonth =
        new Date(Number(year), monthIndex + 1, 0).getDate();

    const totalsByDay = new Map(
        report.daily.map(item => [item.day, item.total])
    );

    const maxTotal = Math.max(1, ...totalsByDay.values());

    for (let day = 1; day <= daysInMonth; day++) {
        const total = totalsByDay.get(day) || 0;
        const column = document.createElement("div");
        column.className = "chart-day";
        column.title = `${day} ${month}: ${money(total)}`;

        const bar = document.createElement("div");
        bar.className = "chart-bar";
        bar.style.height = `${Math.max(3, (total / maxTotal) * 100)}%`;
        bar.setAttribute("aria-label", `${money(total)} on day ${day}`);

        const label = document.createElement("span");
        label.textContent = day;

        column.append(bar, label);
        chart.appendChild(column);
    }

    if (report.count === 0) {
        const note = document.createElement("p");
        note.className = "empty";
        note.textContent = "No expenses recorded for this month.";
        chart.prepend(note);
    }
}

async function refreshDashboard() {
    try {
        await Promise.all([loadExpenses(), loadMonthlyReport()]);
    } catch (error) {
        if (error.message !== "Please log in again.") {
            showMessage(error.message, true);
        }
    }
}

form.addEventListener("submit", async event => {
    event.preventDefault();

    const subject = subjectInput.value.trim();
    const price = Number(priceInput.value);

    if (!subject || !Number.isFinite(price) || price <= 0) {
        showMessage("Enter an expense name and a valid amount.", true);
        return;
    }

    addButton.disabled = true;
    addButton.textContent = "Adding...";

    try {
        await fetchJSON("/api/expenses", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ subject, price })
        });

        form.reset();
        showMessage("Expense added successfully!");
        await refreshDashboard();
    } catch (error) {
        showMessage(error.message, true);
    } finally {
        addButton.disabled = false;
        addButton.textContent = "+ Add Expense";
    }
});

async function addLogoutButton() {
    const header = document.querySelector("header");
    if (!header || document.getElementById("logout-button")) return;

    try {
        const user = await fetchJSON("/api/me");
        const area = document.createElement("div");
        area.style.display = "flex";
        area.style.alignItems = "center";
        area.style.justifyContent = "space-between";
        area.style.gap = "12px";
        area.style.flexWrap = "wrap";

        const greeting = document.createElement("span");
        greeting.textContent = `Logged in as ${user.username}`;

        const button = document.createElement("button");
        button.id = "logout-button";
        button.type = "button";
        button.textContent = "Log out";
        button.style.cursor = "pointer";

        button.addEventListener("click", async () => {
            button.disabled = true;
            try {
                await fetchJSON("/api/logout", { method: "POST" });
                window.location.href = "/login";
            } catch (error) {
                showMessage(error.message, true);
                button.disabled = false;
            }
        });

        area.append(greeting, button);
        header.prepend(area);
    } catch (error) {
        if (error.message !== "Please log in again.") {
            showMessage(error.message, true);
        }
    }
}

addLogoutButton();
refreshDashboard();
