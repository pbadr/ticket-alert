import importlib.util, os
os.environ.setdefault("NTFY_TOPIC", "unused")
s = importlib.util.spec_from_file_location("c", "check.py"); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
m.MUST_CONTAIN = ""  # these films aren't Doomsday; test only the cinema rule
B = "https://universalcinemas.com/browsing/Movies/Details/"
for label, path, code in [("doomsday  @Lahore", "m-HO00001519", "8888"), ("spiderman @Lahore", "h-HO00001418", "8888"),
                          ("wildwood  @Lahore", "h-HO00001597", "8888"), ("wildwood  @Multan", "h-HO00001597", "9999"),
                          ("spiderman @Multan", "h-HO00001418", "9999")]:
    print("RESULT", label, "->", m.check(B + path, code))
m.MUST_CONTAIN = "doomsday"
print("RESULT doomsday real rule ->", m.check(B + "m-HO00001519", "8888"))
