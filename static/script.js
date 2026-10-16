(() => {
    const body = document.body;
    const cartKey = "fruithub-cart-v1";
    const productCards = [...document.querySelectorAll("[data-product-card]")];
    const cartItems = document.querySelector("[data-cart-items]");
    const cartTotal = document.querySelector("[data-cart-total]");
    const checkoutForm = document.querySelector("[data-checkout-form]");
    const checkoutMessage = document.querySelector("[data-checkout-message]");
    const drawer = document.querySelector("[data-cart-drawer]");
    const productData = new Map((window.productCatalog || []).map(product => [product.id, product]));

    let cart = {};
    try {
        const saved = JSON.parse(localStorage.getItem(cartKey) || "{}");
        if (saved && typeof saved === "object" && !Array.isArray(saved)) {
            for (const [id, quantity] of Object.entries(saved)) {
                if (productData.has(id) && Number.isInteger(quantity) && quantity > 0 && quantity <= 99) {
                    cart[id] = quantity;
                }
            }
        }
    } catch {
        localStorage.removeItem(cartKey);
    }

    function saveCart() {
        localStorage.setItem(cartKey, JSON.stringify(cart));
        renderCart();
    }

    function renderCart() {
        const count = Object.values(cart).reduce((sum, quantity) => sum + quantity, 0);
        document.querySelectorAll("[data-cart-count]").forEach(element => {
            element.textContent = count;
        });
        const entries = Object.entries(cart).filter(([id]) => productData.has(id));
        if (cartItems) {
            cartItems.replaceChildren();
            if (!entries.length) {
                const empty = document.createElement("p");
                empty.className = "empty-cart";
                empty.textContent = "Your bag is waiting for something fresh.";
                cartItems.append(empty);
            }
            entries.forEach(([id, quantity]) => {
                const product = productData.get(id);
                const row = document.createElement("div");
                row.className = "cart-line";
                const name = document.createElement("span");
                name.className = "cart-line-name";
                name.textContent = product.name;
                const price = document.createElement("span");
                price.className = "cart-line-price";
                price.textContent = `KES ${(product.price * quantity).toLocaleString()}`;
                const controls = document.createElement("div");
                controls.className = "cart-line-controls";
                const decrease = document.createElement("button");
                decrease.type = "button";
                decrease.textContent = "−";
                decrease.setAttribute("aria-label", `Remove one ${product.name}`);
                decrease.addEventListener("click", () => changeQuantity(id, -1));
                const amount = document.createElement("span");
                amount.textContent = quantity;
                const increase = document.createElement("button");
                increase.type = "button";
                increase.textContent = "+";
                increase.setAttribute("aria-label", `Add one ${product.name}`);
                increase.addEventListener("click", () => changeQuantity(id, 1));
                controls.append(decrease, amount, increase);
                row.append(name, price, controls);
                cartItems.append(row);
            });
        }
        const total = entries.reduce((sum, [id, quantity]) => sum + productData.get(id).price * quantity, 0);
        if (cartTotal) cartTotal.textContent = `KES ${total.toLocaleString()}`;
    }

    function changeQuantity(id, difference) {
        const quantity = (cart[id] || 0) + difference;
        if (quantity < 1) delete cart[id];
        else if (quantity <= 99) cart[id] = quantity;
        saveCart();
    }

    function delay(milliseconds) {
        return new Promise(resolve => window.setTimeout(resolve, milliseconds));
    }

    async function watchPayment(orderId) {
        for (let attempt = 0; attempt < 24; attempt++) {
            await delay(5000);
            try {
                const response = await fetch(`/api/orders/${orderId}`, {
                    headers: { "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content }
                });
                const result = await response.json().catch(() => ({}));
                if (response.status === 401) {
                    window.location.href = `/login?next=${encodeURIComponent("/account")}`;
                    return;
                }
                if (!response.ok) {
                    checkoutMessage.textContent = result.error || "We could not check the payment status. Retrying...";
                    continue;
                }
                if (result.status === "paid") {
                    checkoutMessage.textContent = `Payment received. Order #${orderId} is confirmed.`;
                    return;
                }
                if (result.status === "failed") {
                    checkoutMessage.textContent = `Payment for order #${orderId} was not completed. You can try checkout again.`;
                    checkoutMessage.classList.add("error");
                    return;
                }
                checkoutMessage.textContent = `Waiting for M-Pesa confirmation for order #${orderId}...`;
            } catch {
                checkoutMessage.textContent = "We could not check the payment status. Retrying...";
            }
        }
        checkoutMessage.textContent = `Payment is still pending. You can check order #${orderId} in your account.`;
    }

    function setCartOpen(open) {
        body.classList.toggle("cart-open", open);
        if (drawer) drawer.setAttribute("aria-hidden", String(!open));
    }

    document.querySelectorAll("[data-add-to-cart]").forEach(button => {
        button.addEventListener("click", () => {
            const id = button.dataset.productId;
            if (!productData.has(id)) return;
            if ((cart[id] || 0) < 99) cart[id] = (cart[id] || 0) + 1;
            saveCart();
            setCartOpen(true);
        });
    });
    document.querySelectorAll("[data-open-cart]").forEach(button => button.addEventListener("click", () => setCartOpen(true)));
    document.querySelectorAll("[data-close-cart], [data-cart-backdrop]").forEach(button => button.addEventListener("click", () => setCartOpen(false)));
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") setCartOpen(false);
    });

    const navToggle = document.querySelector("[data-nav-toggle]");
    if (navToggle) {
        navToggle.addEventListener("click", () => {
            const isOpen = body.classList.toggle("nav-open");
            navToggle.setAttribute("aria-expanded", String(isOpen));
        });
    }

    const search = document.querySelector("[data-product-search]");
    if (search) {
        search.addEventListener("input", () => {
            const query = search.value.trim().toLowerCase();
            let visible = 0;
            productCards.forEach(card => {
                const matches = card.dataset.name.includes(query);
                card.hidden = !matches;
                if (matches) visible++;
            });
            const empty = document.querySelector("[data-no-results]");
            if (empty) empty.hidden = visible > 0;
        });
    }

    if (checkoutForm) {
        checkoutForm.addEventListener("submit", async event => {
            event.preventDefault();
            if (body.dataset.authenticated !== "true") {
                window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
                return;
            }
            if (!Object.keys(cart).length) {
                checkoutMessage.textContent = "Add something fresh to your bag first.";
                checkoutMessage.classList.add("error");
                return;
            }
            const button = checkoutForm.querySelector("button[type=submit]");
            const token = document.querySelector('meta[name="csrf-token"]').content;
            button.disabled = true;
            button.firstChild.textContent = "Connecting to M-Pesa...";
            checkoutMessage.textContent = "Please wait while we send a payment request to your phone.";
            checkoutMessage.classList.remove("error");
            try {
                const response = await fetch("/api/checkout", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
                    body: JSON.stringify({
                        phone: checkoutForm.elements.phone.value,
                        items: Object.entries(cart).map(([product_id, quantity]) => ({ product_id, quantity }))
                    })
                });
                const result = await response.json().catch(() => ({}));
                if (response.status === 401) {
                    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
                    return;
                }
                if (!response.ok) throw new Error(result.error || "We could not start your payment.");
                cart = {};
                saveCart();
                checkoutMessage.textContent = `${result.message} Waiting for payment confirmation...`;
                checkoutForm.elements.phone.value = "";
                watchPayment(result.order_id);
            } catch (error) {
                checkoutMessage.textContent = error.message || "We could not reach the payment service. Please try again.";
                checkoutMessage.classList.add("error");
            } finally {
                button.disabled = false;
                button.firstChild.textContent = "Pay with M-Pesa ";
            }
        });
    }

    renderCart();
})();
