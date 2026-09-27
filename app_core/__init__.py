# Модули пакета импортируют Gtk напрямую, поэтому версия фиксируется здесь,
# до первого импорта: иначе при наличии GTK4 PyGObject загрузит его по умолчанию.
try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
except (ImportError, ValueError):
    pass
