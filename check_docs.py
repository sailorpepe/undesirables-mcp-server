import ast

with open("server.py", "r") as f:
    tree = ast.parse(f.read())

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        is_tool = False
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if getattr(dec.func.value, "id", "") == "mcp" and dec.func.attr == "tool":
                    is_tool = True
                    break
        
        if is_tool:
            docstring = ast.get_docstring(node)
            args = [a.arg for a in node.args.args if a.arg != "self"]
            
            if not docstring:
                print(f"❌ {node.name}: Missing entirely")
                continue
                
            missing_args = []
            for arg in args:
                if f"{arg}:" not in docstring and f"{arg} (" not in docstring:
                    missing_args.append(arg)
            
            if missing_args:
                print(f"⚠️ {node.name}: Missing descriptions for {missing_args}")
            else:
                print(f"✅ {node.name}: Complete")
