import json

def get_json_data(path:str):
    try:
        with open(path, "r") as file:
            data = json.load(file)
            return data
    except Exception as e:
        print(f"Error loading json data at path: {path}")

if __name__ == '__main__':
    farms = get_json_data("farms 1.json")
    slaughterhouses = get_json_data("slaughterhouses 1.json")
    transports = get_json_data("transports 1.json")

    print(farms[0])
    

