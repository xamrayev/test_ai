variants_list = ["a","b","c"]
v= "Вариант"
tab_titles = [(f"{v} {chr(65 + i)}") for i in range(len(variants_list))]
for i in tab_titles:
    print(i)

    