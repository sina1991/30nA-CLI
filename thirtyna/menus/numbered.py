def show(session):
    while not session.done:
        print("\n" + session.title)
        items = session.items
        for index, item in enumerate(items, 1):
            print(f"{index}. {item.title}")
        print("0. Back / exit")
        if session.error:
            print(session.error)
        try:
            choice = input("Select: ").strip()
        except EOFError:
            return
        if choice == "0":
            session.back()
        elif choice.isascii() and choice.isdecimal() and len(choice) <= 10 and 1 <= int(choice) <= len(items):
            session.select(items[int(choice) - 1])
        else:
            session.error = "Enter a listed number."
