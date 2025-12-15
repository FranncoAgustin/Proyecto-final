document.addEventListener("DOMContentLoaded", function () {
  const select = document.getElementById("variant-select");
  const image = document.getElementById("product-image");
  const desc = document.getElementById("variant-desc");

  if (!select) return;

  function aplicarVariante(option) {
    // Cambiar imagen
    const imgUrl = option.dataset.image;
    if (imgUrl && image) {
      image.src = imgUrl;
    }

    // Cambiar descripción
    const texto = option.dataset.desc || "";
    if (desc) {
      desc.textContent = texto;
    }
  }

  // 👉 aplicar la variante inicial (la principal)
  aplicarVariante(select.options[select.selectedIndex]);

  // 👉 escuchar cambios
  select.addEventListener("change", function () {
    aplicarVariante(this.options[this.selectedIndex]);
  });

    (function () {
    const select = document.getElementById("variant-select");
    const hidden = document.getElementById("variante_id_input");
    if (!select || !hidden) return;

    hidden.value = select.value;

    select.addEventListener("change", function () {
      hidden.value = this.value;
    });
  })();

});
