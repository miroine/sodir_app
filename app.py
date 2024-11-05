import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from npd_wraper import field

from utils.callbaks_figure import *

#from streamlit_option_menu import option_menu
#from numerize.numerize import numerize
#from query import *
import time



# example get the field data 

#cleamonthly_prod = pd.read_csv("https://factpages.sodir.no/ReportServer_npdpublic?/FactPages/tableview/field_production_monthly&rs:Command=Render&rc:Toolbar=false&rc:Parameters=f&IpAddress=not_used&CultureCode=nb-no&rs:Format=CSV&Top100=false")
@st.cache_data
def _get_data():
    return field().get_field_production_monthly()
monthly_prod = _get_data()

#monthly_prod['date'] = pd.to_datetime(dict(year=monthly_prod.prfYear, month=monthly_prod.prfMonth, day=1))

#monthly_prod.drop(columns = ['prfYear','prfMonth'], inplace =True)
df_info=field().get_field_overview()


# Style
with open('style.css')as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html = True)

#side bar
st.sidebar.image("data/npd.png",caption="Developped byh Merouane Hamdani")


#switcher
st.sidebar.header("Please select columns")

selected_field = st.sidebar.selectbox(
    'OSEBERG',
    df_info['fldName'].unique()
)

#selected_columns=st.sidebar.multiselect(
#    "Select field",
#     options=monthly_prod.columns.to_list(),
#     default=monthly_prod.columns.to_list(),
#)


#st.dataframe (data=monthly_prod.loc[monthly_prod.prfInformationCarrier == selected_field].set_index('date'))


df_selection=monthly_prod.query(
    "prfInformationCarrier==@selected_field"
)

tail_prod = update_tail_production(df_selection)


def main_display():

    st.title ('NPD Field Overview')
    st.header( f"Field {selected_field}")
    s1, s2,s3 = st.columns([4,0.1,4])

    with s1: 
        st.info(get_field_info(selected_field))
    
    with s3:
        map_html = field_map(selected_field)
        st.markdown(map_html, unsafe_allow_html=True)

    with st.expander("Monthly Production Data"):
        showData=st.multiselect('Filter: ',tail_prod.columns,default=tail_prod.columns.to_list())
        st.dataframe(tail_prod[showData],use_container_width=True)

    #compute top analytics
    total_oil_production = float(df_selection['prfPrdOilNetMillSm3'].sum())
    total_gas_production = float(df_selection['prfPrdGasNetBillSm3'].sum())
    total_ngl_production = float(df_selection['prfPrdNGLNetMillSm3'].sum())
    total_condensate_production = float(df_selection['prfPrdCondensateNetMillSm3'].sum())
    total_water_production = float(df_selection['prfPrdProducedWaterInFieldMillSm3'].sum())

    total1,total2,total3,total4,total5=st.columns(5,gap='small')
    with total1:
        st.info('Oil',icon="📌")
        st.metric(label="Msm3",value=f"{total_oil_production:,.1f}")

    with total2:
        st.info('Gas',icon="📌")
        st.metric(label="Gsm3",value=f"{total_gas_production:,.1f}")

    with total3:
        st.info('NGL',icon="📌")
        st.metric(label="Mtonns",value=f"{total_ngl_production:,.1f}")

    with total4:
        st.info('Cnd',icon="📌")
        st.metric(label="Msm3",value=f"{total_condensate_production:,.1f}")

    with total5:
        st.info('Water',icon="📌")
        st.metric(label="Msm3",value=f"{total_water_production:,.1f}")

    st.markdown("""---""")

    st.header( f"Reserve plot")
    s1, s2=st.columns(2,gap='small')

    with s1:
        st.plotly_chart(callback_plot_reserve(selected_field),use_container_width=True)
    with s2:
        st.plotly_chart(callback_plot_gas(selected_field),use_container_width=True)


main_display()

def get_description(selected_field):
    s1, s2=st.columns(2,gap='small')
    df_info=field().get_field_description()
    df_info=df_info[df_info.fldName==selected_field]
    s='''
    %s   
    '''%(df_info[df_info.fldDescriptionHeading.str.contains("Development")].fldDescriptionText.values[0])
    with s1:
        st.header("Development")
        st.markdown(s)
    with s2:
        st.header("Status")
        s='''
        %s   
        '''%(df_info[df_info.fldDescriptionHeading.str.contains("Status")].fldDescriptionText.values[0])
        st.markdown(s)
    s1, s2, s3=st.columns(3,gap='small')
    with s1:
        st.header("Reservoir")
        s='''
        %s   
        '''%(df_info[df_info.fldDescriptionHeading.str.contains("Reservoir")].fldDescriptionText.values[0])
        st.markdown(s)
    with s2:
        st.header("Recovery")
        s='''
        %s   
        '''%(df_info[df_info.fldDescriptionHeading.str.contains("Recovery")].fldDescriptionText.values[0])
        st.markdown(s)
    with s3:
        st.header("Transport")
        s='''
        %s   
        '''%(df_info[df_info.fldDescriptionHeading.str.contains("Transport")].fldDescriptionText.values[0])
        st.markdown(s)

get_description(selected_field)



#graphs

def graphs():

    try:
        fig_oil= fig_plot_oil(df_selection)
    except:
        pass
    
    try:
        fig_gas= fig_plot_gas(df_selection)
    except:
        pass

    s1=st.columns(1)
    s2=st.columns(1)
    s3 = st.columns(1)
    try:
        s1 [0].plotly_chart(fig_oil,use_container_width=True)
    except:
        pass
    try:
        s2 [0].plotly_chart(fig_gas,use_container_width=True)
    except:
        pass
    try:
        s3 [0].plotly_chart(callback_investments(selected_field), use_container_width=True)
    except:
        pass

       
graphs()

# add investment predictions + table with production and exploration wells 
# add map with well locations
