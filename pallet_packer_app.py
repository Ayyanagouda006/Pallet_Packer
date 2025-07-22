import streamlit as st
import pandas as pd
import math
from io import BytesIO

# Constants
PALLET_LENGTH = 122
PALLET_WIDTH = 102
PALLET_HEIGHT = 194

# --- Safe carton packing logic ---
def calculate_cartons_per_layer(carton_L, carton_W):
    try:
        carton_L = float(carton_L)
        carton_W = float(carton_W)
        if carton_L <= 0 or carton_W <= 0:
            return 0, (0, 0)
    except (ValueError, TypeError):
        return 0, (0, 0)

    orientations = [(carton_L, carton_W), (carton_W, carton_L)]
    max_count = 0
    best_orientation = (0, 0)
    for l, w in orientations:
        try:
            count_L = PALLET_LENGTH // l
            count_W = PALLET_WIDTH // w
            total = count_L * count_W
            if total > max_count:
                max_count = total
                best_orientation = (l, w)
        except ZeroDivisionError:
            continue
    return max_count, best_orientation

def pack_fba_group(group_df):
    group_df['Volume'] = group_df['Length'] * group_df['Width'] * group_df['Height']
    group_df = group_df.sort_values(by='Volume', ascending=False).reset_index(drop=True)
    pallets = []
    pallet_id = 1
    remaining_cartons = group_df.copy()

    while remaining_cartons['# of Cartons'].sum() > 0:
        height_used = 0
        max_length_used = 0
        max_width_used = 0
        pallet_summary = {
            'FBA Code': remaining_cartons['FBA Code'].iloc[0],
            'Pallet #': pallet_id,
            'Packed Cartons': 0,
            'Details': [],
            'Total Height Used': 0,
            'Total Length Used': 0,
            'Total Width Used': 0
        }

        for idx, row in remaining_cartons.iterrows():
            if row['# of Cartons'] <= 0:
                continue

            cartons_per_layer, (used_L, used_W) = calculate_cartons_per_layer(row['Length'], row['Width'])
            if cartons_per_layer == 0:
                continue

            max_layers = (PALLET_HEIGHT - height_used) // row['Height']
            max_cartons = cartons_per_layer * max_layers
            cartons_to_pack = min(row['# of Cartons'], max_cartons)
            if cartons_to_pack == 0:
                continue

            layers_used = math.ceil(cartons_to_pack / cartons_per_layer)
            height_add = layers_used * row['Height']
            if height_used + height_add > PALLET_HEIGHT:
                continue

            # Pack cartons
            remaining_cartons.at[idx, '# of Cartons'] -= cartons_to_pack
            height_used += height_add
            pallet_summary['Packed Cartons'] += cartons_to_pack

            count_L = PALLET_LENGTH // used_L
            count_W = PALLET_WIDTH // used_W
            rows_used = math.ceil(min(cartons_to_pack, cartons_per_layer) / count_L)

            length_occupied = min(PALLET_LENGTH, count_L * used_L)
            width_occupied = min(PALLET_WIDTH, rows_used * used_W)

            max_length_used = max(max_length_used, length_occupied)
            max_width_used = max(max_width_used, width_occupied)

            pallet_summary['Details'].append({
                'Carton Size': f"{row['Length']}x{row['Width']}x{row['Height']}",
                'Packed': cartons_to_pack
            })

        if pallet_summary['Packed Cartons'] > 0:
            pallet_summary['Total Height Used'] = height_used
            pallet_summary['Total Length Used'] = max_length_used
            pallet_summary['Total Width Used'] = max_width_used
            pallets.append(pallet_summary)
            pallet_id += 1
        else:
            break

    return pallets

def pack_all(df):
    all_pallets = []
    for fba_code, group in df.groupby("FBA Code"):
        pallets = pack_fba_group(group.copy())
        all_pallets.extend(pallets)
    return all_pallets

def convert_to_excel(result):
    df_out = pd.DataFrame(result)
    df_out = df_out.astype(str)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_out.to_excel(writer, sheet_name='Palletization Output', index=False)
    output.seek(0)
    return output

# ---------------------- Streamlit UI ----------------------

st.title("📦 Palletization Tool (FBA Wise)")
st.write("Upload an Excel or CSV file containing FBA carton data.")

uploaded_file = st.file_uploader("Upload File", type=["xlsx", "csv"])

# Provide a downloadable template
template = pd.DataFrame(columns=['FBA Code', '# of Cartons', 'Length', 'Width', 'Height'])
template_io = BytesIO()
with pd.ExcelWriter(template_io, engine='xlsxwriter') as writer:
    template.to_excel(writer, index=False)
template_io.seek(0)

st.download_button(
    label="📥 Download Uploading Template",
    data=template_io,
    file_name="Palletization_Template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        # Clean column names
        df.columns = df.columns.str.strip()

        # Ensure required columns are present
        required_columns = {'FBA Code', '# of Cartons', 'Length', 'Width', 'Height'}
        if not required_columns.issubset(df.columns):
            st.error(f"Missing required columns: {required_columns - set(df.columns)}")
        else:
            # Type conversion
            df['FBA Code'] = df['FBA Code'].astype(str)
            for col in ['# of Cartons', 'Length', 'Width', 'Height']:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # Filter invalid rows
            df = df.dropna(subset=['# of Cartons', 'Length', 'Width', 'Height'])
            df = df[(df['# of Cartons'] > 0) & (df['Length'] > 0) & (df['Width'] > 0) & (df['Height'] > 0)]

            st.success("File uploaded successfully!")
            st.subheader("📋 Preview of Uploaded Data")
            st.dataframe(df.head())

            result = pack_all(df)

            if result:
                st.subheader("📦 Palletization Summary")
                result_df = pd.DataFrame(result)
                result_df = result_df.astype(str)
                st.dataframe(result_df)

                excel_file = convert_to_excel(result_df)
                st.download_button(
                    label="📥 Download Excel File",
                    data=excel_file,
                    file_name="Palletization_Output.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("No cartons could be packed into pallets.")
    except Exception as e:
        st.error(f"❌ Error processing file: {e}")
