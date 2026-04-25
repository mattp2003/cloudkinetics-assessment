from ck_agent.agent import AgentSession


def main():
    print("CloudKinetics agent (local). Type 'quit' to exit.\n")
    session = AgentSession()
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in {"quit", "exit", "q"}:
            break
        if not user_input:
            continue
        reply = session.handle_user_message(user_input)
        print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    main()
