import server

if __name__ == "__main__":
    server.enable_memory_lock()
    server.main()
    server.mcp.run(transport="stdio")
