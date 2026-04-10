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

if [ "$1" == "" ]; then
    echo Please specify a folder.
    exit
fi

cd $1
for file in $(find . -type f 2>/dev/null); do
    confirm_and_cp "$file" "/$file"
done

