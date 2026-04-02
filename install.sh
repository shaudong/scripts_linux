confirm_and_cp() {
    local src=$1
    local dest=$2
    
    read -p "cp $src $dest ? (y/n): " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp -i "$src" "$dest"
    fi
    echo "--------------------------------"
}

for file in $(find etc usr -type f 2>/dev/null); do
    confirm_and_cp "$file" "/$file"
done

