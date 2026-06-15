from src.agent import ask_agent

def main():
    print("Hello from RenxinOS Agent!")

    while True:
        user_input = input("你 > ")
        if user_input.lower() == "exit":
            break

        reply = ask_agent(user_input)
        print(f"Agent > {reply}\n")


if __name__ == "__main__":
    main()